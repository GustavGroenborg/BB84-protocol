import json
import logging
import os
import sys
import threading
from datetime import datetime
from typing import Dict, Any

from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.fake_provider import FakeFez
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit.primitives import BackendSamplerV2

from src.arg_parser import parse_args
from src.person import Eavesdropper, Person
from src.socket import Socket

MAX_QUBITS = 156

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s,%(msecs)0d] %(message)s",
        datefmt="%H:%M:%S"
    )
    args = parse_args()

    if args.online:
        response = input("Running circuit on real quantum hardware. Confirm to proceed (y/n): ").strip().lower()
        if response == "y":
            setup = setup_quantum_computer(args)
        else:
            print("Please restart program.")
            sys.exit(1)
    else:
        print("Running circuit on local simulator")
        setup = setup_simulator(args)

    for i in range(args.repeat):
        run_test(args, setup, i)

def run_test(args, setup: Dict[str, Any], test_number=None):
    delta = 1
    sift_factor = 4
    key_length  = args.key_length
    num_qubits  = (sift_factor * delta) * key_length
    if num_qubits > MAX_QUBITS:
        print(f"Requested too may qubits. Max qubits: {MAX_QUBITS}")
        sys.exit(1)
    print(f"num qubits: {num_qubits}")
  
    socket = Socket()
    alice = Person("Alice", num_qubits, socket)
    bob   = Person("Bob", num_qubits, socket, setup=setup, generate_bits=False)
    eve   = Eavesdropper("Eve", num_qubits, bob.name, socket, setup=setup)
    
    alice.transmit_states()
    threads = [ ]
    if args.with_eve: threads.append(threading.Thread(target=eve.listen))
    threads.append(threading.Thread(target=alice.listen))
    threads.append(threading.Thread(target=bob.listen))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    test_results = [ ]
    if args.with_eve:
        test_results.append(match_bits(alice, bob))
        test_results.append(match_bits(eve, alice))
        test_results.append(match_bits(eve, bob))
    else:
        test_results.append(match_bits(alice, bob))

    if args.results_path:
        data = {
            'test_name': f"{args.test_name}{test_number or ''}",
            'data': datetime.now().isoformat(),
            'num_qubits': num_qubits,
            'key_length': key_length,
            'optimise': setup["optimise"],
            'results': test_results
        }
        append_results(args.results_path, data)
    

def match_bits(person_a: Person, person_b: Person) -> Dict[str, Any]:
    matches = 0
    for (a, b) in zip(person_a.key, person_b.key):
        if a == b: matches += 1

    results = {
        'person_a': {
            'name': person_a.name,
            'bases': person_a.bases,
            'bits': person_a.bits,
            'key': person_a.key,
        },
        'person_b': {
            'name': person_b.name,
            'bases': person_b.bases,
            'bits': person_b.bits,
            'key': person_b.key,
        },
        'fidelity': matches / len(person_a.key),
        'loss': 1 - matches / len(person_a.key)
    }
        
    print(f"{person_a.name}'s key: {person_a.key}")
    print(f"{person_b.name}'s key:   {person_b.key}")
    print(f"Key length:  {len(person_a.key)}")
    print("Fidelity: ", results["fidelity"])
    print("Loss:     ", results["loss"])
    print("---------------------")

    return results

def append_results(filepath: str, new_result: Dict[str, Any]):
    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            try:
                data = json.load(file)
                if not isinstance(data, list):
                    data = [data]
            except json.JSONDecodeError:
                data = [ ]
    else:
        data = [ ]

    data.append(new_result)
    with open(filepath, 'w') as file:
        json.dump(data, file, indent=4)
                

    
def setup_quantum_computer(args) -> Dict[str, Any]:
    service = QiskitRuntimeService(
        channel="ibm_quantum_platform",
        token=args.ibm_token,
        instance=args.crn
    )
    backend = service.backend(args.qpu, instance=args.crn)
    sampler = SamplerV2(backend)
    return {
        "service": service,
        "backend": backend,
        "sampler": sampler,
        "optimise": args.optimise
    }


def setup_simulator(args) -> Dict[str, Any]:
    if args.noiseless is True:
        backend_sim = AerSimulator()
        sampler = BackendSamplerV2(backend=backend_sim)
    else:
        fake_backend = FakeFez()
        noise_model  = NoiseModel.from_backend(fake_backend)
        backend_sim  = AerSimulator(noise_model=noise_model)
        sampler      = BackendSamplerV2(backend=backend_sim)

    return {
        "service": None,
        "backend": backend_sim,
        "sampler": sampler,
        "optimise": args.optimise
    }

if __name__ == "__main__":
    main()
 
