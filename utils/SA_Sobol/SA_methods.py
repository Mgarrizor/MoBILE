
import csv
import os
import argparse 
import subprocess
from typing import List

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
                if len(row) < 4:
                    continue

                # 1. Name (string)
                name = row[0].strip()
                names.append(name)

                # 2. p1 and p2 (floats)
                try:
                    # Convert to float to preserve the numerical property
                    p1 = float(row[1].strip())
                    p2 = float(row[2].strip())
                    bounds.append([p1, p2])
                except ValueError as e:
                    print(f"Warning: Could not convert bounds to float for row starting with '{name}'. Error: {e}")
                    continue # Skip to the next row if conversion fails

                # 3. dist (string)
                dist = row[3].strip()
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

    params["ncore"]=1                      # Default number of processes
    params["samples"]='sample_values.txt'  # Default path to generated sample
    params["problem"]='SA_params.txt'      # Dafault path to MOBILE parameters
    params["dfields"]='driving_fields/'    # Dafault path to MOBILE's driving fields (t2m, rainfall, pop, area)
    params["run"]=True                     # Run simulations
    
    return params

#===============================================================================
def get_command_line_args():
    """
    Loads default values and sets new ones based on input from flags.
    """
    default_params = defaults()
    
    parser = argparse.ArgumentParser(
        description="Sobol Sensitivity Analysis script.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    #
    parser.add_argument('--ncore',   type=int, default=default_params["ncore"], help='Number of processes (default: %(default)s)')
    parser.add_argument('--samples', type=str, default=default_params["samples"], help='Path to generated sample (default: %(default)s)')
    parser.add_argument('--problem', type=str, default=default_params["problem"], help='Problem parameters (default: %(default)s)')
    parser.add_argument('--dfields', type=str, default=default_params["dfields"], help='Path to driving fields (default: %(default)s)')
    parser.add_argument('--run',     type=str, default=default_params["run"], help='Run models (default: %(default)s)')
    
    # Parse arguments
    args = parser.parse_args()

    return args

#===============================================================================
def run(irun):
    """
    ------------------------
    Run the model & post-process results 
    ------------------------
    - Run model with the 'i'-th combination of the 'names' parameter values, 'ivals', read from the Sobol sample.
    - The model runs using the driving fields located at 'data_loc'.

    1) Create in/out directories & parameter file
    2) Create run command
    3) Log run info into .info file
    4) Execute commmand
    5) Post-processing

    """
    names=irun[0]   # - Names of parameters involved in the Sensitivity Analysis
    i=irun[1]       # - We need the index as the samples should be written back in the same order 
                    #   they were generated. This is an idiosyncrasy of the
                    #   Sobol analysis, and we are using an unordered parallelization that will dump results
                    #   in a mixed order. We'll save this number in the corresponding folder name.
    ivals=irun[2]   # - Parameter values for i-th run.
    data_loc=irun[3]# - Location of driving fields (rainfall, t2m, pop, area)
    #------------------------
    # 1) Create input and output directories,
    #    as well as the parameter file, 'params.txt', for this run
    #
    indir=f'./input/input_sample{i}/'
    outdir=f'./output/mobile_SA_sample{i}'
    subprocess.run(['mkdir','-p',indir])       # - The flag -p enables the command
    subprocess.run(['mkdir','-p','./output'])  #   to create parent directories as necessary.
    subprocess.run(['rm','-rf',outdir])        # - Remove folder to be sure, otherwise, if the NetCDF
                                               #   file already exists the model won't run.

    f=open(indir+'params.txt','w')             # - Create parameter file. Overwrites existing file.
    
    for indx,val in enumerate(ivals):          # - Write down the parameters being analysed for their sensitivity.
        f.write(f"{names[indx]}={val},\n")     #   These will be read from 'params.txt' via 
    f.close()                                  #   the "-c" flag when executing MoBILE.
    #===============================================================
    
    # 2) Create run command
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
                                 '-n','365',    # Integration length --> If  = 0  then takes length of driving fields
                                 '-u','1',       # Spin Up 0: No Spin Up ; 1 Spin Up to tolerance 'eps' (hard wired for now)
                                 '-d','1',       # Disease ID 0: Cholera ; 1: Malaria ; 2: Dengue (non-functional)
                                 '-v','1',       # 0: VECTRI is NOT active ; 1: VECTRI is active
                                 '-m','0',       # 0: Mobility is NOT active ; 1: Mobility is active
                                 '-a','4500',   # Number of agents in simulation
                                 '-s','12345',   # Seed for reproducibility of results
                                 '-i','NONE',    # Immunity forcing
                                 '-l','namelist'+str(i)+'.nml',
                                 #
                                 # Output folder
                                 '-o',outdir]

    # 3) Save run info
    
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

    # 4) Execute commmand
    for attempt in range(2):
        with open(indir+f'stdout-file{i}.txt', 'w') as f_out:
            with open(indir+f'stderr-file{i}.txt', 'w') as f_err:
                result = subprocess.run(command, stdout=f_out, stderr=f_err)   # Redirect sdout & sterr to .txt files 
               # subprocess.run(command)
            #   subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            break
        else:
            print(f"\nCommand failed on first attempt (run: {i} --> re-trying)")
    else:
        print(f"\nCommand failed on both attempts (run: {i} --> is invalid)")
    return 1


#===============================================================================
def post_processing(irun):
    """
    Post-processing. Specific to the SA being performed.
    One should modify this function to generate the desired metric, i.e.,
    annual EIR 'cdo -yearsum ...', etc.
    """
    names=irun[0]   # - Names of parameters involved in the Sensitivity Analysis
    i=irun[1]       # - We need the index as the samples should be written back in the same order 
                    #   they were generated. This is an idiosyncrasy of the
                    #   Sobol analysis, and we are using an unordered parallelization that will dump results
                    #   in a mixed order. We'll save this number in the corresponding folder name.
    ivals=irun[2]   # - Parameter values for i-th run.
    data_loc=irun[3]# - Location of driving fields (rainfall, t2m, pop, area)

    outdir=f'./output/mobile_SA_sample{i}' # Location of the ouput NetCDF file
    subprocess.run(['ncks','-6','-O',outdir+'/mobile_SA_sample'+str(i)+'.nc',
                                     outdir+'/mobile_SA_sample'+str(i)+'_3.nc'])
    subprocess.run(['cdo','-O','-L',
                          '-yearsum','-selvar,EIR',
                            outdir+'/mobile_SA_sample'+str(i)+'_3.nc',
                            outdir+'/yearmean'+str(i)+'_3.nc',
                                      ], stdout=subprocess.DEVNULL)
    return 1

def read(irun):

    i=irun[0]
    outdir=f'./output/mobile_SA_sample{i}' # Location of the ouput NetCDF file
    file_name=outdir+'/yearmean'+str(i)+'_3.nc'
    
    #
    val = subprocess.run(['cdo','-output',
                            file_name],
                            capture_output=True,
                            text=True)
    
    return float(val.stdout.strip())
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












