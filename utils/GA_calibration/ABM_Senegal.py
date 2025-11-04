#!/usr/bin/python3

import xarray as xr
import numpy as np
import pandas as pd
import os
import subprocess
from scipy.stats import chi2
from scipy.stats import pearsonr
from scipy.stats import ttest_1samp as ttest1
import logging
import sys

def init():
    global prep_sim, biasfile

    prep_sim = True
   # biasfile = open("bias_file.txt","w")
    input_parfile  = './Senegal_par.txt'
    return input_parfile

def vname(imem,igen): 
    # Each member and generation is stored with a fixed name format. Create
    # the string of simulaton (imem,igen).
    return('./output/mobile_mon_gen{}_mem{}'.format(igen,imem))

def sname(imem,igen): 
    # Each member and generation is stored with a fixed name format. Create
    # the string of simulaton (imem,igen).
    return('./output/mobile_mon_gen{}_mem{}/mobile_mon_gen{}_mem{}.nc'.format(igen,imem,igen,imem))

def get_ready(ncfile,vals,imem):
    # User-specific function to modify ABM's output before
    # comparing it to the observed data set.


    # Back to NetCDF3 to manipulate with cdo ---------------------------------------------
    subprocess.run(['ncks','-O','-6',ncfile,'temp'+str(imem)+'.nc'])

    # We need the annual Plasmodium falciparum EIR 
    subprocess.run(['cdo','-O','-L','-timmean','-yearsum','temp'+str(imem)+'.nc','meanyearsum_'+str(imem)+'.nc'])
    
    # Clean up and return -----------------------------------------------------------------
    subprocess.run(['mv','meanyearsum_'+str(imem)+'.nc',ncfile])
    subprocess.run(['rm','temp'+str(imem)+'.nc'])
             
    return ncfile

def skill_map(imem,igen,vals):
    # imem : Ensemble member index
    # igen : Generation number
    
    vectri_dir = os.environ['MOBILE'] # Path to MOBILE (environmental variable pointing to ...)              
     
    #data_obs = xr.open_dataset(vectri_dir+'/../data_Italy/egg_count_Italy.nc')

    #=========== Metric 1 =======================================================
    # Annual PfEir against human population density [ref: Kelly-Hope 2009]
    data_obs_mean = pd.read_csv('cal_data/Kelly-Hope_2009/values.csv',header=None)
    data_obs_std = pd.read_csv('cal_data/Kelly-Hope_2009/SD.csv',header=None)

    APf_EIR = np.array(data_obs_mean[1])
    APf_EIR_SD = np.array(data_obs_std[1]) - APf_EIR
    
    # Open simulated output (MoBILE) ==============================
    ncfile=sname(imem,igen)
  #  indir='./input_mem{}/'.format(imem)

    if True:
    #    ncfile   = get_ready(ncfile,vals,imem)
        data_sim = xr.open_dataset(get_ready(ncfile,vals,imem))
    #    data_sim = xr.open_dataset(ncfile)
    #    data_sim = data_sim["eggs"]
    else:
        data_sim = xr.open_dataset(ncfile)
    #    data_sim = data_sim["eggs"]
    #    data_sim = xr.open_dataset(ncfile)["eggs"]

    AEIR = data_sim["EIR"].dropna(dim="time")
    pop  = data_sim["pop"]

    pop_range = [0,100,200,500,1000,5000,10000]
    pop_cntres = 0.5*(pop_range+np.roll(pop_range,1))[1:]

    AEIR_mean = np.zeros((len(pop_cntres)))
    AEIR_std = np.zeros((len(pop_cntres)))

    for j in range(len(pop_cntres)):
        AEIR_mean[j] = AEIR.where((pop>pop_range[j]) & (pop <= pop_range[j+1])).mean()
        AEIR_std[j] = AEIR.where((pop>pop_range[j]) & (pop <= pop_range[j+1])).std()

    chi2_score=np.sum(((APf_EIR-AEIR_mean)/(np.sqrt(APf_EIR_SD**2+AEIR_std**2)))**2)
    pval_chi2 = chi2.sf(x=chi2_score,df=len(pop_cntres))
    #============================================================================
    #=========== Metric 2 =======================================================


    #============================================================================
    # Return pvals
    stats={"rmse":1-pval_chi2,"bias":0,"bpval":0,"r2pval":0,"rval":0}

    return (stats)


def run(imem,igen,vals,data_loc):  # Practically untouched from Adrian's version
    # --> Run an ensemble member of the model
    #
    # Make the options file for this member ========================
    #
    indir='./input_mem{}/'.format(imem)
    ofile=vname(imem,igen)
    subprocess.run(['mkdir','-p',indir])       # The flag -p enables the command
    subprocess.run(['mkdir','-p','./output'])  # to create parent directories as necessary.
    subprocess.run(['rm','-f',ofile])          # Clean file to be sure, otherwise, if the 
                                               # file already exists the model won't run.

    f=open(indir+'params.txt','w')             # Overwrites existing file.
    
    for val in vals:                               # Write down the parameters being calibrated.
        f.write("{}={},\n".format(val,vals[val]))  # They are passed via params.txt with 
    f.close()                                      # the "-c" flag when executing MoBILE.
    #===============================================================
    # Run the model 
    #
    mobdir=os.environ['MOBILE']
    
    command=['bash',mobdir+'/mobile.sh','-c',indir+'params.txt',             # File with model parameters
                                 #
                                 '-t',data_loc+'t2m_cal.nc',   # Temperature file
                                 '-r',data_loc+'rain_cal.nc',  # Rainfall file
                                 '-p',data_loc+'pop_cal.nc',   # Population file
                                 '-x',data_loc+'area.nc',      # Area file
                                 #
                                 #
                                 '-n','0',       # Integration length --> If  = 0  then takes length of driving fields
                                 '-u','0',       # Spin Up 0: No SU ; 1 SU to tolerance
                                 '-d','1',       # Disease ID 0: Cholera ; 1: Malaria
                                 '-v','1',       # VECTRI is active
                                 '-m','0',       # Mobility is inactive
                                 '-a','500000',  # Number of agents in simulation
                                 '-s','12345',   # Seed for reproducibility of results
                                 #
                                 #
                                 '-o',ofile]

    with open(indir+'stdout-file{}.txt'.format(imem), 'w') as f:
      #  subprocess.run(command, stdout=f)   # Redirect sdout to .txt file
        subprocess.run(command)
    print ("model run",imem,"complete")
    # Postrun processing ------> Is now in the get_ready function
    #===================================================







