"""
Optuna wrapper

Source: https://optuna.readthedocs.io/en/stable/index.html#


"""

#===== Import libraries
import os, sys, time
import numpy as np
import optuna

import multiprocessing
from tabulate import tabulate
#===== Import modules
import CA_methods

# Tasks

# - Create unique filenames for this specific trial
# - Restore optimization from csv file

optuna.logging.set_verbosity(optuna.logging.WARNING)

def main(args):


    # Safety check (no more cores than those available)
    npro=min(args.njobs,int(multiprocessing.cpu_count()))
    #
    print(f'Cores = {npro} \nPath to parameter file: {args.problem}')
    #
    problem = CA_methods.read_problem_file(args.problem) # load problem params, since we need the param names
    


    temp_dict = { key : value for key, value in problem.items() if key not in ('num_vars')}
    print(tabulate(temp_dict, headers="keys", tablefmt="heavy_grid"))


	# If we're not loading --> delete the study if it exists
    if (args.load == 'False'):
        
        try:
            optuna.delete_study(study_name=args.name, storage=args.sname)
        except KeyError:
            # If the study doesn't exist, just catch the error and move on
            pass
    
    #sampler = optuna.samplers.CmaEsSampler(
    #                         n_startup_trials=150,
    #                         warn_independent_sampling=True
    #                         )
    

    sampler = optuna.samplers.TPESampler(
                            n_startup_trials=150, 
                            multivariate=True  # Highly recommended for non-linear/correlated params
                           )
    study = optuna.create_study(
        storage=args.sname,         # Specify the storage URL here.
        study_name=args.name,       # Name of study
        load_if_exists=args.load,   #
        direction="minimize",        # 
        sampler=sampler
    )
    # sampler=optuna.samplers.CmaEsSampler()

    print(f"Sampler is {study.sampler.__class__.__name__}")

    if (args.load == 'True'):
        print(f"Study continued. Previous trials found: {len(study.trials)}")
    
    
    study.optimize(CA_methods.wrap_objective(problem, args.dfields), n_trials=args.ntrials, n_jobs = npro, 
                   show_progress_bar=True,
                   callbacks=[CA_methods.wrap_snapshot_callback(args.nsave)])
    
    print(f"Best parameters: {study.best_params}")
    print(f"Best score: {study.best_value}")

    best_params = study.best_params

    # Write best parameters
    with open('best_params.txt', 'w') as f:
        for indx, name in enumerate(problem['names']):
            # Pull the best value for this specific parameter name
            val = best_params[name]
            
            # Write using the required syntax
            f.write(f"{name}={val},\n")
    
#===============================================================================
if __name__ == "__main__":

    print('\n============ Run Optimization ====================')
    multiprocessing.set_start_method('fork', force=True)
    args=CA_methods.get_command_line_args()
    main(args)
    
#===============================================================================


















