#!/bin/bash 

param_file=SA_params.txt
driving_fields='driving_fields/'
#driving_fields='../calibration/driving_fields/'
N=10
generate=true
run=true
main_run=True
analyze=true
parallel=true  # MOBILE parallelism (not the parallelism from the SA! This  handles the number of threads
               # in the agent loop for a SINGLE, individual run.)
nthreads=1
ncores=10        # Number of processes (this is the parallelism for the SA, with multiple
                # simulataneous runs)
samples_path=sample_values.txt

# Open MP parallelisation
if ( $parallel ) ; then
    echo '-- MoBILE being run in parallel mode --'
    export NPROC=$(getconf _NPROCESSORS_ONLN)
    export OMP_NUM_THREADS=$(getconf _NPROCESSORS_ONLN)
    export OMP_NUM_THREADS=${nthreads}
    #export NPROC=1
    echo 'Number of available processors =' ${NPROC}
    echo 'Number of used threads = ' ${OMP_NUM_THREADS}
    echo '---------------------------------------'
else
    echo '-- MoBILE being run in serial mode --'
    export OMP_NUM_THREADS=1
fi


if ( $generate ) ; then
python3 <<EOF

# ---- Import libraries ----
import numpy as np
import sys 
import pprint
from tabulate import tabulate

from SALib.sample import sobol as sample_sobol

# ---- Import modules ----
import SA_methods
#=========================

print('\n============ 1/4 Define Model Inputs ====================')
# --- Execute reading function and print the result ---

problem = SA_methods.read_problem_file('${param_file}')

if problem is None:
    # If None is returned (due to file not found, IOError, or bad data),
    # print a final message and exit the program immediately.
    print(f"\nFATAL: Failed to load configuration from {FILE_NAME}. Exiting.")
    sys.exit(1) # Use 1 to indicate an error state
print("\n--- Configuration Loaded Successfully ---")

temp_dict = { key : value for key, value in problem.items() if key not in ('num_vars')}
print(tabulate(temp_dict, headers="keys", tablefmt="heavy_grid"))

print('\n============ 2/4 Generate Samples ====================')
sample_values = sample_sobol.sample(problem, 2**${N})
print(f'\n U matrix: {sample_values.shape}')
#print(sample_values)

# Since the model is not written in Python we save the sample values in a text file
# Each line in sample_values.txt is one input of the model.
np.savetxt("${samples_path}", sample_values)
EOF
fi

if ( $run ) ; then

python3 SA_Sobol.py --ncore=${ncores} --samples=${samples_path} \
                                      --problem=${param_file} \
                                      --dfields=${driving_fields} \
                                      --run=${main_run}
                            #    > stdout.txt 
                                # --lparallel=${parallel} 
fi

if ( $analyze ) ; then
python3 <<EOF
print('\n============ 4/4 Analyze Model Outputs ====================')
from SALib.analyze import sobol as anal_sobol
import numpy as np
# ---- Import modules ----
import SA_methods
#=========================

problem = SA_methods.read_problem_file('${param_file}')
Y = np.loadtxt("Y_values.txt", float)
Si = anal_sobol.analyze(problem, Y)

np.set_printoptions(precision=4,suppress=True) #suppress=True avoid exponential notation

print('\n First order indices')
print(Si['S1'])

print('\n Total order indices')
print(Si['ST'])

print("x1-x2:", Si['S2'][0,1])
print("x1-x3:", Si['S2'][0,2])
print("x2-x3:", Si['S2'][1,2])


import matplotlib.pyplot as plt
Si.plot()
plt.show()

EOF
fi






