#!/usr/bin/env python

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import afqmcpy

model = {
    'name': 'Hubbard',
    't': 1.0,
    'U': 1,
    'nx': 4,
    'ny': 1,
    'nup': 1,
    'ndown': 1
}
qmc_options = {
    'method': 'CPMC',
    'dt': 0.01,
    'nsteps': 100,
    'nmeasure': 10,
    'nwalkers': 4,
    'rng_seed': 7,
    'temperature': 0.0
}
# Set up the calculation state, i.e., model + method + common options
state = afqmcpy.state.State(model, qmc_options)
# Print out calculation information for posterity
afqmcpy.info.print_header(state)
# Run QMC calculation printing to stdout
afqmcpy.qmc.do_qmc(state)
