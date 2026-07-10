"""
Sobol Sensitivity Analysis

- Sobol's method is a model-agnostic variance-based sensitivity analysis, where
the contribution of each model parameter to the total variance (of a chosen metric) 
is calculated. 
- The contribution is typically evaluated with three indices, ...
- These indices are estimated from a set of simulations whose set of parameters are
generated following the 'pick-and-freeze' method.

"""

#===== Import libraries
import os, sys, time
import numpy as np
import multiprocessing
from tqdm import trange
from multiprocessing import Pool
#===== Import modules
import SA_methods

def main(args):

    # Safety check (no more cores than those available)
    npro=min(args.ncore,int(multiprocessing.cpu_count()))
    #
    print(f'Cores = {npro} \nPath to sample file: {args.samples} \nPath to parameter file: {args.problem}')

    problem = SA_methods.read_problem_file(args.problem) # load problem params, since we need the param names
    vals = np.loadtxt(args.samples, float)               # read Sobol sample

    print(f"Model parameters: {problem['names']}")

    pfinished=0             # Counter for progress bar
    ptotal=len(vals)        # Counter for progress bar
    control_0 = time.time() # Timer 

    with Pool(processes=npro) as pl:     # Open pool of npro processes to compute in parallel
        
        if (args.run == 'True'):
            # Run model --------------------------------------
            print('\n-- Running models --')
            # Pick up the results without waiting for the rest to finish (return of .run function = 1)
            for result in pl.imap_unordered(SA_methods.run, [[problem['names'],i, vals[i], args.dfields] for i in range(len(vals))]):      
            
                pfinished += result # Add the result (=1) to the counter to have a global progress bar
                
                # Show progress via stdout as well as in file 'outfile'
                print(f'\r{pfinished:.0f}/{ptotal:.0f} - {pfinished/ptotal*100:.2f} %', end='', flush=True) 
                with open ('model_progress'+".txt", "w") as outfile:
                    outfile.write(f'Progress bar {pfinished/ptotal*100:.3f} % ; Elapsed time {(time.time()-control_0)/60:.2f} minutes \n')
                    outfile.close()
            # End of generator (no need to call pl.join()) ---

        # Post-processing --------------------------------
        print('\n-- Post-processing runs --')
        pfinished=0  
        control_0 = time.time() 
        #
        for result in pl.imap_unordered(SA_methods.post_processing, [[problem['names'],i, vals[i], args.dfields] for i in range(len(vals))]):      
        
            pfinished += result # Add the result (=1) to the counter to have a global progress bar
            
            # Show progress via stdout as well as in file 'outfile'
            print(f'\r{pfinished/ptotal*100:.2f} %', end='', flush=True) 
            with open ('post_process_progress'+".txt", "w") as outfile:
                outfile.write(f'Progress bar {pfinished/ptotal*100:.3f} % ; Elapsed time {(time.time()-control_0)/60:.2f} minutes \n')
                outfile.close()
        # End of generator (no need to call pl.join()) ---
    
    # Write values in sequential mode
    Y_vals = np.zeros(len(vals))

    for i in trange(len(vals)):
        Y_vals[i] =  SA_methods.read([i, outfile])

    np.savetxt("Y_values.txt", Y_vals)

    return


if __name__ == "__main__":

    print('\n============ 3/4 Run Model ====================')
    args=SA_methods.get_command_line_args()
    main(args)




