"""Explicit batch runner; the notebook uses src.main for exactly one experiment."""
import argparse
from .main import run

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--configs',nargs='+',required=True)
    parser.add_argument('--output',default='results')
    args=parser.parse_args()
    failed=False
    for config in args.configs:
        folder,result=run(config,args.output)
        print(folder,result['status'])
        failed |= result['status'] in ('REJECTED','LICENSE_SIZE_EXCEEDED','NO_SOLUTION','UNSUPPORTED')
    return 2 if failed else 0
if __name__=='__main__':
    raise SystemExit(main())
