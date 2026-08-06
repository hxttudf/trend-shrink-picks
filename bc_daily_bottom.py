#!/usr/bin/env python3
"""wrapper: exec真身(单一代码源trend-shrink-picks, venv解释器)"""
import os, sys
_VENV = "/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3"
_REAL = f"/home/ubuntu/trend-shrink-picks/{os.path.basename(sys.argv[0]).replace('.py','')}.py"
os.execv(_VENV, [_VENV, _REAL] + sys.argv[1:])
