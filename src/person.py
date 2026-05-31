from __future__ import annotations

import logging
import numpy as np
import re
import time
from enum import IntEnum
from typing import Any, Dict, List, Optional

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, generate_preset_pass_manager

from src.socket import Message, Socket

MAX_LOSS = 0.1

class MeasurementBase(IntEnum):
    Z = 0
    X = 1

class PrefixAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"{self.extra['prefix']}: {msg}", kwargs # type: ignore

class Person:
    def __init__(self, name: str, str_len: int, socket: Socket, setup: Optional[Dict[str, Any]]=None, generate_bits=True):
        self.bases = self._generate_bit_string(str_len)
        self.bits = self._generate_bit_string(str_len) if generate_bits else [ ]
        self.key = []
        self.name = name
        self.test_bits = []

        self._time_stamp = 0
        self._setup = setup
        self._socket = socket

        self.log = PrefixAdapter(
            logging.getLogger(__name__),
            {"prefix": self.name}
        )

    def __str__(self) -> str:
        return (
            f"\t--- Person ---\n"
            f"\tbits:    {self.bits}\n"
            f"\tbases:   {self.bases}\n"
            f"\tkey:     {self.key}\n"
            f"\t--------------"
        )

    def listen(self):
        self.log.info("Listening on socket.")
        running = True
        while running:
            if self._socket.classic_channel.latest_time_stamp() <= self._time_stamp:
                self.log.info("Waiting to receive message...")
                time.sleep(0.2)
            else:
                msg = self._read_classic()
                running = self._handle_message(msg)

        self.log.info("Received stop flag, shutting down.")

    def transmit_states(self):
        bb84_circuit = self._prepare_states()
        
        self.log.info("Transmitting qubits through quantum channel")
        self._socket.quantum_channel.transmit(bb84_circuit)

        self._announce_classic(
            Message.Header.REQUEST_OK,
            "states received",
        )

    def _handle_message(self, msg: Message) -> bool:
        match msg.header:
            case Message.Header.ABORT:
                # Retry not implemented
                return False
            
            case Message.Header.BASES:
                assert isinstance(msg.content, list)
                self.log.info("Reading bases retrieved through classic channel")
                discarded_bases = self._read_bases_and_discard(msg.content)
                self._announce_discarded_bases(discarded_bases)
                return True
                
            case Message.Header.BIT_CHECK:
                assert isinstance(msg.content, list)
                self.log.info("Reading bit check through classic channel")
                test_bits = self._check_bits(msg.content)
                self._announce_test_bits(test_bits)
                return True

            case Message.Header.CONFIRM_OK:
                assert isinstance(msg.content, str)
                return self._handle_confirm_ok(msg.content)
            
            case Message.Header.DISCARDED_BITS:
                assert isinstance(msg.content, list)
                self.log.info("Reading discarded bits through classic channel")
                self._discard_bits_and_bases(msg.content)
                self._announce_bit_check()
                return True
            
            case Message.Header.REQUEST_OK:
                assert isinstance(msg.content, str)
                return self._handle_request_ok(msg.content)
            
            case Message.Header.TEST_BITS:
                assert isinstance(msg.content, list)
                self.log.info("Reading test bits through classic channel")
                loss = self._compare_test_bits(msg.content)
                self._announce_test_bit_loss(loss)
                return True
            
        return False

    def _handle_request_ok(self, msg_content: str) -> bool:
        match msg_content:
            case "states received":
                self._receive_and_measure()
                self._announce_classic(Message.Header.CONFIRM_OK, "states received")
                return True
            
            case _:
                if "loss" in msg_content:
                    loss_confirmed = self._confirm_loss(msg_content)
                    if loss_confirmed:
                        self.log.info("Protocol finished")
                    # Returns false regardless of the result, in order to stop the proccess
                    return False
                else:
                    self.log.error(f"Received unexpected REQUEST_OK content: {msg_content}")
                    return False

    def _handle_confirm_ok(self, msg_content: str) -> bool:
        match msg_content:
            case "states received":
                self._announce_bases()
                return True
            case _:
                if "loss" in msg_content:
                    self.log.info("Protocol finished.")
                    return False
                else:
                    self.log.error(f"Received unexpected CONFIRM_OK content: {msg_content}")
                    return False

    ### Quantum circuit of BB84-protocol ###
    
    def _prepare_states(self) -> QuantumCircuit:
        self.log.info("Preparing states")
        num_qubits = len(self.bases)
        bb84_circuit = QuantumCircuit(num_qubits, num_qubits)
        
        for n in range(num_qubits):
            match (self.bits[n], self.bases[n]):
                case (1, 0):
                    bb84_circuit.x(n)
                case (0, 0):
                    pass
                case (1, 1):
                    bb84_circuit.x(n)
                    bb84_circuit.h(n)
                case (0, 1):
                    bb84_circuit.h(n)

        return bb84_circuit

    def _receive_and_measure(self):
        if self._setup is None: raise ValueError("'self._setup' is 'None'. Cannot perform measurement")
        
        self.log.info("Receiving qubits through quantum channel")
        bb84_circuit = self._socket.quantum_channel.receive()
        assert bb84_circuit is not None
        
        num_qubits = bb84_circuit.num_qubits
        for n in range(num_qubits):
            if self.bases[n] == MeasurementBase.X:
                bb84_circuit.h(n) # Flipped due to hardware limitations
            bb84_circuit.measure(n, n)

        self.log.info("Measuring states")
        result = self._run_circuit(bb84_circuit, self._setup)
        self._process_result(result)

    def _process_result(self, result):
        big_endian_bits = list(result[0].data.c.get_counts().keys())[0]
        self.bits = [int(i) for i in reversed(big_endian_bits)]

    @staticmethod
    def _run_circuit(qc: QuantumCircuit, setup: Dict[str, Any]):
        if setup["optimise"]:
            if setup["service"] is not None:
                preset_pass_manager = generate_preset_pass_manager(
                    target=setup["backend"].target,
                    optimization_level=setup["optimise"]
                )
            else:
                preset_pass_manager = generate_preset_pass_manager(
                    optimization_level=setup["optimise"]
                )
            
            optimised_circuit = preset_pass_manager.run(qc)
            job = setup["sampler"].run([optimised_circuit], shots=1)
        else:
            job = setup["sampler"].run([qc], shots=1)
        
        return job.result()

    def _check_bits(self, indices: List[int]) -> List[int]:
        test_bits = [bit for i, bit in enumerate(self.key) if i in indices]
        self._discard_key_indices(indices)
        return test_bits

    def _compare_test_bits(self, incomming_bits: List[int]) -> float:
        matches = 0
        for (a, b) in zip(self.test_bits, incomming_bits):
            if a == b:
                matches += 1
        loss = 1 - matches / len(self.test_bits)
        return loss

    def _confirm_loss(self, msg_content: str) -> bool:
        match = re.search(r"(\w+):\s*([\d.]+)", msg_content)
        if match:
            key = match.group(1)
            value = float(match.group(2))
            self.log.info(f"Matched key: '{key}', value: '{value}'")
        else:
            raise ValueError(f"Expected key-value match in string: {msg_content}")

        if key == "loss" and value < MAX_LOSS:
            self._announce_classic(
                Message.Header.CONFIRM_OK,
                msg_content
            )
            return True
        else:
            self._announce_classic(
                Message.Header.ABORT,
                msg_content
            )
            return False

    def _discard_bits_and_bases(self, discarded_indices: List[int]):
        self.log.info(f"Discarding bit and base indices: {discarded_indices}")
        self.bits  = [bit for i, bit in enumerate(self.bits) if i not in discarded_indices]
        self.bases = [base for i, base in enumerate(self.bases) if i not in discarded_indices]

    def _discard_key_indices(self, discarded_indices: List[int]):
        self.log.info(f"Discarding indices in key: {discarded_indices}")
        self.key = [bit for i, bit in enumerate(self.key) if i not in discarded_indices]

    def _read_bases_and_discard(self, incomming_bases: List[int]) -> List[int]:
        discarded_indices = [ ]
        for n in range(len(incomming_bases)):
            if self.bases[n] == incomming_bases[n]:
                self.key.append(self.bits[n])
            else:
                discarded_indices.append(n)
        
        self._discard_bits_and_bases(discarded_indices)
        return discarded_indices

    @staticmethod
    def _generate_bit_string(length: int) -> List[int]:
        return np.random.randint(2, size=length).tolist()

    def _announce_bases(self):
        self.key = self.bases
        self._announce_classic(Message.Header.BASES, self.bases)

    def _announce_bit_check(self):
        self.key = self.bits
        mid = len(self.bits) // 2
        self.test_bits = [bit for i, bit in enumerate(self.key) if i in range(mid)]
        self._discard_key_indices(list(range(mid)))
        self._announce_classic(
            Message.Header.BIT_CHECK,
            list(range(mid)),
        )

    def _announce_discarded_bases(self, discarded_indices: List[int]):
        self._announce_classic(
            Message.Header.DISCARDED_BITS,
            discarded_indices
        )

    def _announce_test_bits(self, test_bits: List[int]):
        self._announce_classic(
            Message.Header.TEST_BITS,
            test_bits
        )

    def _announce_test_bit_loss(self, loss:float):
        self._announce_classic(
            Message.Header.REQUEST_OK,
            f"loss: {loss}"
        )

    def _announce_classic(self, header: str, content:  str | List[int]):
        self._time_stamp += 1
        msg = Message(
            self.name,
            header,
            content,
            self._time_stamp
        )
        self._socket.classic_channel.announce(msg)
        self.log.info(f"Announced message on classic channel\n{msg}\n{self}")

    def _read_classic(self) -> Message:
        msg = self._socket.classic_channel.read()
        self._time_stamp = max(self._time_stamp, msg.time_stamp) + 1
        return msg


class Eavesdropper(Person):
    def __init__(self, name: str, str_len: int, target: str, socket: Socket, setup: Dict[str, Any]):
        super().__init__(name, str_len, socket, setup=setup, generate_bits=False)
        self._stolen_message = None
        self._target = target
        self._transmission_intercepted = False

    def listen(self):
        self.log.info("Listening on socket.")
        while self._socket.classic_channel.latest_time_stamp() <= self._time_stamp:
            self.log.info("Waiting to receive message...")
            time.sleep(0.1)

        self.log.info("Stealing message from classic channel")
        self._stolen_message = self._read_classic()
        # Setting time stamp to 0, in order to fool Bob into thinking no message has been sent
        self._socket.classic_channel._latest_time_stamp = 0

        # Listening in on the quantum transimission
        self._receive_and_measure()
        self._transmit_states()
        self._silent_announcement(self._stolen_message)

        #self.log.info("Interrupted quantum transmission. Shutting down")
        self._transmission_intercepted = True
        running = True
        while running:
            if self._socket.classic_channel.latest_time_stamp() <= self._time_stamp:
                self.log.info("Waiting to receive message...")
                time.sleep(0.1)
            elif self._target in self._peek_classic_sender():
                msg = self._read_classic()
                running = self._handle_message(msg)

    def _transmit_states(self):
        bb84_circuit = self._prepare_states()
        self.log.info("Transmitting qubits through quantum channel")
        self._socket.quantum_channel.transmit(bb84_circuit)

    def _silent_announcement(self, msg: Message):
        self._time_stamp = msg.time_stamp
        self._socket.classic_channel.announce(msg)

    def _announce_classic(self, header: str, content: str | List[int]):
        if not self._transmission_intercepted:
            return super()._announce_classic(header, content)
        
    def _read_classic(self) -> Message:
        msg = self._socket.classic_channel._queue[-1]
        self._time_stamp = msg.time_stamp
        return msg

    def _peek_classic_sender(self) -> str:
        return self._socket.classic_channel._queue[-1].sender
