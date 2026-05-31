import argparse
import os
import sys
from dotenv import load_dotenv

def parse_args():
    parser = argparse.ArgumentParser(
        description="Simple CLI to execute BB84 protocol."
    )

    parser.add_argument("--ibm-token", type=str, default=None,
                        help="Token to access IBM Quantum platform. Can be omitted if the envorinment variable 'IBM_TOKEN' is specified.")

    parser.add_argument("--crn", type=str, default=None,
                        help="CRN used to connect to an IBM Quantum Instance. Can be omitted if the environment variable 'CRN' is specified.")

    parser.add_argument("--qpu", type=str, default="ibm_fez",
                        choices=["ibm_kingston", "ibm_fez", "ibm_marrakesh"],
                        help="The QPU that the circuit is executed on, if online execution is chosen.")

    parser.add_argument("--key-length", type=int, default=6,
                        help="Desired key length of final key. Please note that a higher key length will result in longer execution time!")

    parser.add_argument("--results-path", type=str,
                        help="Path where the results of the run should be stored.")
    parser.add_argument("--repeat", type=int, default=1,
                        help="The number of times the test should be repeated.")
    parser.add_argument("--test-name", type=str,
                        help="The name of the test. Used for storing the results.")

    parser.add_argument("--with-eve", action="store_true",
                        help="Whether or not to eavesdrop on the circuit")

    optimisation_group = parser.add_mutually_exclusive_group()
    optimisation_group.add_argument("-O-1", dest="optimise",
                                    action="store_const", const=None,
                                    help="No optimisation, nor transpilation. This option does only work with the flag '--noiseless'.")
    optimisation_group.add_argument("-O0", dest="optimise", action="store_const", const=0, help="No optimisation, transpilation only")
    optimisation_group.add_argument("-O1", dest="optimise", action="store_const", const=1, help="Light optimisation and transpilation")
    optimisation_group.add_argument("-O2", dest="optimise", action="store_const", const=2, help="Medium optimisation and transpilation")
    optimisation_group.add_argument("-O3", dest="optimise", action="store_const", const=3, help="High optimisation and transpilation")
    parser.set_defaults(optimise=0)
    
    setup_settings = parser.add_mutually_exclusive_group()
    setup_settings.add_argument("--online", action="store_true",
                                help="If set, runs the circuit on a quantum computer at IBM.")
    setup_settings.add_argument("--noiseless", action="store_true",
                                help="If, set, runs the simulator without a noise model.")

    args = parser.parse_args()

    if args.optimise is None and args.noiseless is not True:
        parser.error("'-O-1' must be used in conjunction with '--noiseless'")

    if args.online and args.qpu is not None:
        _ensure_tokens(args)

    if args.results_path and not args.test_name:
        parser.error("'--results-path' requires '--test-name' to be set.")
    
    return args


def _ensure_tokens(args):
    load_dotenv()
    if args.ibm_token is None:
        args.ibm_token = os.getenv("IBM_TOKEN")
    if args.crn is None:
        args.crn = os.getenv("CRN")

    if args.ibm_token is None or args.crn is None:
        if args.ibm_token is not None:
            ibm_status = "defined"
        else:
            ibm_status = "undefined"

        if args.crn is not None:
            crn_status = "defined"
        else:
            crn_status = "undefined"
        print(f"Tokens not provided! IBM Token is {ibm_status}. CRN is {crn_status}.")
        sys.exit(1);
