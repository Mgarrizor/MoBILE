import numpy as np
from scipy.stats import truncnorm, lognorm
import subprocess
import os
import argparse 
import csv
from typing import List
import xarray as xr
import pandas as pd

import threading

# Create a global lock
netcdf_lock = threading.Lock()
#===============================================================================
def read_problem_file(file_path):
    """
    Reads problem data from a file path, parses it, and returns a dictionary.

    Args:
        file_path (str): The path to the text file (e.g., "SA_params.txt").

    Returns:
        dict: The parsed problem data dictionary, or None if the file cannot be read.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at path: {file_path}")
        return None

    names = []
    bounds = []
    dists = []

    try:
        # Open the file for reading ('r')
        with open(file_path, 'r') as file:
            # Use csv.reader to handle the parsing
            # 'skipinitialspace=True' handles the extra whitespace
            reader = csv.reader(file, skipinitialspace=True)

            # Skip the header row
            try:
                next(reader)
            except StopIteration:
                print("Warning: File is empty.")
                return { 'num_vars': 0, 'names': [], 'bounds': [], 'dists': [] }

            # Process data rows
            for row in reader:
                # Ensure the row has enough elements
                if len(row) < 6:
                    continue

                # 1. Name (string)
                name = row[0].strip()
                names.append(name)

                # 2. p1, p2, p3 and p4 (floats)
                try:
                    # Convert to float to preserve the numerical property
                    p1 = float(row[1].strip())
                    p2 = float(row[2].strip())
                    p3 = float(row[3].strip())
                    p4 = float(row[4].strip())
                    bounds.append([p1, p2, p3, p4])

                except ValueError as e:
                    print(f"Warning: Could not convert bounds to float for row starting with '{name}'. Error: {e}")
                    continue # Skip to the next row if conversion fails

                # 3. dist (string)
                dist = row[5].strip()
                dists.append(dist)

    except IOError as e:
        print(f"Error reading file: {e}")
        return None

    # Construct the final dictionary
    problem = {
        'num_vars': len(names),
        'names': names,
        'bounds': bounds,
        'dists': dists
    }

    return problem

#===============================================================================
def defaults():
    """
    Sets default argument values.
    """
    params={}

    mobile_dir = os.environ.get('MOBILE', '.') # MOBILE path

    params["problem"]='CA_params.txt' # Dafault path to MOBILE parameters
    params["njobs"]=1          # Default number of processes
    params["ntrials"]=500      # Default number of runs
    params["nsave"]=200        # Default frequency for snapshot
    params["load"]=False       # Default to new study
    params["name"]='test'      # Default name of optimization study
    params["storage_name"]='sqlite:///default_storage.db' # Default name for storage
    params["dfields"]='driving_fields/'    # Dafault path to MOBILE's driving fields (t2m, rainfall, pop, area)

    return params

#===============================================================================
def get_command_line_args():
    """
    Loads default values and sets new ones based on input from flags.
    """
    default_params = defaults()
    
    parser = argparse.ArgumentParser(
        description="Optuna Parameter Calibration script.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    #
    parser.add_argument('--njobs',   type=int, default=default_params["njobs"], help='Number of processes (default: %(default)s)')
    parser.add_argument('--ntrials', type=int, default=default_params["ntrials"], help='Number of iterations (default: %(default)s)')
    parser.add_argument('--nsave',   type=int, default=default_params["nsave"], help='Snapshot frequency (default: %(default)s)')
    parser.add_argument('--load',    type=str, default=default_params["load"], help='Load previous optimization (default: %(default)s)')
    parser.add_argument('--name',    type=str, default=default_params["name"], help='Name of study (default: %(default)s)')
    parser.add_argument('--sname',   type=str, default=default_params["storage_name"], help='Storage name (default: %(default)s)')
    parser.add_argument('--problem', type=str, default=default_params["problem"], help='Problem parameters (default: %(default)s)')
    parser.add_argument('--dfields', type=str, default=default_params["dfields"], help='Path to driving fields (default: %(default)s)')
    
    # Parse arguments
    args = parser.parse_args()

    return args

#===============================================================================

# Optuna expects the callback function to have a very specific 
# signature: exactly two arguments (study and trial). To pass extra 
# arguments, like frequency, we use a wrapper function.
def wrap_snapshot_callback(frequency):
    # Define a snapshot callback with frequency 'nsave'
    def snapshot_callback(study, trial):
        # Save every 'nsave' trials
        if trial.number % frequency == 0:
            df = study.trials_dataframe()
            df.to_csv("study_snapshot.csv", index=False)
            print(f"--> Snapshot saved at Trial {trial.number}")

    return snapshot_callback
# 
#===============================================================================
def wrap_objective(problem,dfields):
    # In Optuna the 'objective' function demands a single argument --> 'trial'
    # To allow for multiple inputs we wrap it 
    def objective(trial):

        # Index
        # 1.0) Prepare run
        # 1.1) Draw values of calibration parameters &
        #    create parameter text file for MOBILE
        # 1.2) Run MOBILE
        # 2) Post-process results --> return metric

        # Get trial ID to generate folder and filenames 
        trial_ID = int(trial.number)
                                                   
        # 1)
        run(trial, trial_ID, problem, dfields)
    
        # 2) Post-process results --> return metric
    
        return metric(trial_ID)



    return objective
#===============================================================================


def prepare(trial,name,dist,bounds):

    # Args
    # name:   parameter name --> needed to feed into the suggest_float function
    # dist:   string of sampling distribution = [unif, logunif, norm, lognorm]
    #
    # bounds: distribution parameters. If Uniform or log-Uniform the
    #         forst two are used as the lower and upper bounds, respectively. 
    #         If normally or log-normally distributed then the third and fourth
    #         parameters are the mean and standard deviation of a distribution 
    #         truncated by the first and second bounds.
    #
    #   U(a,b)    --> bound1 = a, bound2 = b
    #   N(mu,std) --> bound1 = lower truncation 
    #                 bound2 = upper truncation 
    #                 bound3 = mu 
    #                 bound4 = std
    #                 
    # Draw from given distribution and parameter bounds
    
    if (dist == 'unif'):
        # --- Uniform ---
        # Standard bounded uniform
        p = trial.suggest_float(name, bounds[0], bounds[1])
        #
    elif (dist == 'logunif'):
        # --- Log-Uniform ---
        # 
        p = trial.suggest_float(name, bounds[0], bounds[1], log=True)
        #
    elif (dist == 'norm'):
        # --- (Truncated) Normal ---
        # 
        # Draw U(0,1)
        u_norm = trial.suggest_float(name, 0, 1)
        # Remap to required interval U(a,b)
        vmin, vmax, mu, sigma = bounds
        a, b = (vmin - mu) / sigma, (vmax - mu) / sigma
        # Use scipy's truncnorm to remap into a truncated normal distribution
        p = truncnorm.ppf(u_norm, a, b, loc=mu, scale=sigma)
        #

    elif (dist == 'lognorm'):
        # --- Log-Normal (Bounded) ---
    
        # Draw U(0,1)
        u_norm = trial.suggest_float(name, 0, 1)
        # Remap to required interval U(a,b)
        vmin, vmax, mu, sigma = bounds

        vmin_log = np.log(vmin)
        vmax_log = np.log(vmax)

        if ((mu < vmin_log) | (mu > vmax_log)):
            error_msg = (f"\n[FATAL ERROR] mu = '{mu}' is lesser of greater than bounds '{vmax}' or '{vmin} when log-scaled'.\n"
                     f"Choose value from: log(min) = {vmin_log} to log(max) = {vmax_log}")
            raise ValueError(error_msg)
        
        # Calculate truncation limits in log-space
        a, b = (vmin_log - mu) / sigma, (vmax_log - mu) / sigma

        # Use scipy's truncnorm to remap into a truncated normal distribution
        p = np.exp(truncnorm.ppf(u_norm, a, b, loc=mu, scale=sigma))

    else:
        error_msg = (f"\n[FATAL ERROR] Distribution '{dist}' for parameter '{name}' is not available.\n"
                     "Choose from: [unif, logunif, norm, lognorm]")
        raise ValueError(error_msg)
    return p


def run(trial, trialID, problem, dfields):

    # 1.0) Prepare run directives and parameters
    #    - Create input and output directories,
    #      as well as the parameter file, 'params.txt', for the run 'trialID'
    #
    indir=f'./input/input_sample{trialID}/'
    outdir=f'./output/mobile_CA_sample{trialID}'
    subprocess.run(['mkdir','-p',indir])       # - The flag -p enables the command
    subprocess.run(['mkdir','-p','./output'])  #   to create parent directories as necessary.
    subprocess.run(['rm','-rf',outdir])        # - Remove folder to be sure, otherwise, if the NetCDF
                                               #   file already exists the model won't run.

    # 1.1) Draw values of calibration parameters &
    #    create parameter text file for MOBILE
    f=open(indir+'params.txt','w')                 # - Create parameter file. Overwrites existing file.
    for indx,name in enumerate(problem['names']):  # - Write down the parameters being calibrated.
                                                   #   These will be read from 'params.txt' via 
                                                   #   the "-c" flag when executing MoBILE.
        
        f.write(f"{name}={prepare(trial,name,problem['dists'][indx],problem['bounds'][indx])},\n")     
        
    f.close() 

    # -- Prepare run command --
    
    data_loc = dfields          # Location of driving fields
    mobdir=os.environ['MOBILE'] # Read MOBILE's environmental variable, which points to the location of 
                                # the bash script that runs the program (mobile.sh).

    command=['bash',mobdir+'/mobile.sh',
                                 # File with model parameters
                                 '-c',indir+'params.txt',
                                 #
                                 # Driving fields
                                 '-t',data_loc+'t2m_SA.nc',   # Temperature file
                                 '-r',data_loc+'rain_SA.nc',  # Rainfall file
                                 '-p',data_loc+'pop_SA.nc',   # Population file
                                 '-x',data_loc+'area_SA.nc',  # Area file
                                 #
                                 # Run parameters
                                 '-n','0',       # Integration length --> If  = 0  then takes length of driving fields
                                 '-u','1',       # Spin Up 0: No Spin Up ; 1 Spin Up to tolerance 'eps' (hard wired for now)
                                 '-d','1',       # Disease ID 0: Cholera ; 1: Malaria ; 2: Dengue (non-functional)
                                 '-v','1',       # 0: VECTRI is NOT active ; 1: VECTRI is active
                                 '-m','0',       # 0: Mobility is NOT active ; 1: Mobility is active
                                 '-a','4500',   # Number of agents in simulation
                                 '-s','12345',   # Seed for reproducibility of results
                                 '-i','NONE',    # Immunity forcing
                                 '-l','namelist'+str(trialID)+'.nml',
                                 #
                                 # Output folder
                                 '-o',outdir]

    # Save run info

    log_command_info(
        command_list=['Command:',*command],
        output_filepath=outdir+'.info',
        mode='w') # Write mode -- overwrites existing file.

    # -- Git information -- 
    # 'subprocess.run()' sees the first element of the list as the command to execute, so we need to 
    # run the git command first, save its output and then feed the resulting string into the
    # echo command. Otherwise, if we were to directly feed a single string into .run(), with multiple elements to be
    # executed (echo + git), the first (the echo command) would just print a string (without executing
    # the git command).
    git_command=subprocess.run(['git','--git-dir='+mobdir+'/.git','tag'],
                                    capture_output=True, # Capture the output stream
                                    text=True,)          # Make it a string
    log_command_info(                                    # Now log it into the .info file
    command_list=['Version:',git_command.stdout.strip()],
    output_filepath=outdir+'.info',
    mode='a')                                            # Append mode -- appends to existing file.

    git_command=subprocess.run(['git','-C',mobdir,'remote','get-url','origin'],
                                    capture_output=True, 
                                    text=True,)          
    log_command_info(
    command_list=['Retrieved from:',git_command.stdout.strip()],
    output_filepath=outdir+'.info',
    mode='a')

    date_command=subprocess.run(['date'],
                                    capture_output=True, 
                                    text=True,)          
    log_command_info(
    command_list=['Date:',date_command.stdout.strip()],
    output_filepath=outdir+'.info',
    mode='a')

    # 1.2) Run MOBILE
    # Execute commmand
    for attempt in range(2):
        with open(indir+f'stdout-file{trialID}.txt', 'w') as f_out:
            with open(indir+f'stderr-file{trialID}.txt', 'w') as f_err:
                result = subprocess.run(command, stdout=f_out, stderr=f_err)   # Redirect sdout & sterr to .txt files 
              #  result = subprocess.run(command, stdout=f_out)   # Redirect sdout & sterr to .txt files 
               
               # subprocess.run(command)
            #   subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # If run was successful
        if result.returncode == 0:
            break
        # Otherwise we'll try again, as some failures are caused by racing conditions
        # in the source code (likely while creating symbolic links).
        else:
            print(f"\nCommand failed on first attempt (run: {trialID} --> re-trying)")
    else:
        print(f"\nCommand failed on both attempts (run: {trialID} --> is invalid)")

    return    
                              
def metric(trialID):

    """
    Post-processing. Specific to the Calibration being performed.
    One should modify this function to generate the desired metric, i.e.,
    annual EIR 'cdo -yearsum ...', etc.
    """

    # Revert to NetCDF3 format (not hierarchies) so that cdo manipulation is allowed
    outdir=f'./output/mobile_CA_sample{trialID}' # Location of the ouput NetCDF file
    subprocess.run(['ncks','-6','-O',outdir+'/mobile_CA_sample'+str(trialID)+'.nc',
                                     outdir+'/mobile_CA_sample'+str(trialID)+'_3.nc'])
    
    # Calculate multi-year monthly mean and std
    subprocess.run(['cdo','-O','-L',
                          '-ymonmean','-selvar,hbr',
                            outdir+'/mobile_CA_sample'+str(trialID)+'_3.nc',
                            outdir+'/ymonmean'+str(trialID)+'_3.nc',
                                      ], stdout=subprocess.DEVNULL)

    subprocess.run(['cdo','-O','-L',
                          '-ymonstd','-selvar,hbr',
                            outdir+'/mobile_CA_sample'+str(trialID)+'_3.nc',
                            outdir+'/ymonstd'+str(trialID)+'_3.nc',
                                      ], stdout=subprocess.DEVNULL)


    # Load processed NetCDF file
    ncfile = outdir+'/ymonmean'+str(trialID)+'_3.nc'
    # 
    with netcdf_lock:
        mean_sim = np.array(xr.open_dataset(ncfile)['hbr'])[:,0,0]


    ncfile = outdir+'/ymonstd'+str(trialID)+'_3.nc'
    with netcdf_lock:
        std_sim = np.array(xr.open_dataset(ncfile)['hbr'])[:,0,0]

    # Calibration data (Trape et al. 2014)

    # Anopheles gambiae human biting rate
    DF_gambiae_obs_mean = pd.read_csv('cal_data/mean_gambiae.csv',header=None)
    DF_gambiae_obs_std = pd.read_csv('cal_data/std_gambiae.csv',header=None)

    mean_gambiae = np.array(DF_gambiae_obs_mean[1])
    std_gambiae  = np.array(DF_gambiae_obs_std[1]) - mean_gambiae

    # Anopheles funestus human biting rate 
    DF_funestus_obs_mean = pd.read_csv('cal_data/mean_funestus.csv',header=None)
    DF_funestus_obs_std = pd.read_csv('cal_data/std_funestus.csv',header=None)

    mean_funestus = np.array(DF_funestus_obs_mean[1])
    std_funestus  = np.array(DF_funestus_obs_std[1]) -  mean_funestus

    # Total human biting rate
    obs_mean = mean_funestus + mean_gambiae
    # Error propagation of the sum
    obs_std  = np.sqrt(std_funestus**2+std_gambiae**2)
    #
    RMSE = np.mean(np.sqrt((obs_mean-mean_sim)**2))
    #
    # We renormalize it to have a per-month measure
    return RMSE

#===============================================================================
# Define the utility function to log the command
def log_command_info(
    command_list: List[str],
    output_filepath: str,
    mode: str  # Use 'w' for overwrite (>) or 'a' for append (>>)
):
    """
    Runs an 'echo' command to log info of the executed program
    into the specified file using the given write ('w' or 'a') mode.
    """
    
    # 1. Define the command to be logged (e.g., echo Command: arg1 arg2...)
    echo_command = ['echo', *command_list] # Use '*' to unroll list
    
    # 2. Open the file using the specified mode ('w' or 'a')
    # Note: 'encoding="utf-8"' is good practice for text files
    try:
        with open(output_filepath, mode, encoding="utf-8") as outfile:
            
            # 3. Use subprocess.run and re-direct the 'echo' output to the file 'outfile'
            subprocess.run(
                echo_command,
                stdout=outfile,       # Re-direct output to the file
                check=True            # Raise error if 'echo' fails
            )
        
    except:
        # Catch errors if the command itself returns a non-zero exit code
        print(f"Error: logging command failed")
#===============================================================================





















