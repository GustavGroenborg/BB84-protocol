from collections import deque
from enum import StrEnum
from qiskit import QuantumCircuit
from typing import List

class Message:
    class Header(StrEnum):
        ABORT = "abort protocol"
        BASES = "base announcement"
        BIT_CHECK = "bit check indices announcement"
        CONFIRM_OK = "confirm ok announcement"
        DISCARDED_BITS = "discarded bits announcement"
        REQUEST_OK = "request ok announcement"
        TEST_BITS = "test bits anouncement"

    def __init__(self, sender: str, header: str, content: str | List[int], time_stamp: int):
        self.sender  = sender
        self.header  = header
        self.content = content
        self.time_stamp = time_stamp

    def __str__(self) -> str:
        return (
            f"\t--- Message ---\n"
            f"\tSender:    {self.sender}\n"
            f"\tTime:      {self.time_stamp}\n"
            f"\tHeader:    {self.header}\n"
            f"\tContent:   {self.content}\n"
            f"\t---------------"
        )

class ClassicChannel:
    def __init__(self):
        self._queue = deque()
        self._latest_time_stamp = 0

    def announce(self, msg: Message):
        self._queue.append(msg)
        self._latest_time_stamp = msg.time_stamp

    def latest_time_stamp(self) -> int:
        return self._latest_time_stamp

    def read(self) -> Message:
        return self._queue.pop()

class QuantumChannel:
    def __init__(self):
        self.eavesdropped  = False
        self._in_transmit  = None

    def transmit(self, circuit: QuantumCircuit):
        self._in_transmit = circuit

    def receive(self) -> QuantumCircuit | None:
        circuit = self._in_transmit
        self._in_transmit = None
        return circuit

class Socket:
    def __init__(self):
        self.classic_channel = ClassicChannel()
        self.quantum_channel = QuantumChannel()
