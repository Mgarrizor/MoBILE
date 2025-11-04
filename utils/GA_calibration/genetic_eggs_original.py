#!/usr/bin/python3

"""programme to implement constrained genetic algorithm to calibrate any nonlinear code"""
import numpy as np
import ast
from itertools import islice, cycle
from copy import copy,deepcopy
import getopt, sys, csv
from bisect import bisect
from statistics import mean
import pandas as pd
import scipy.stats as stats
import codecs,json
import subprocess
import multiprocessing
import time
import heapq
from tensorboardX import SummaryWriter    # 2023 M.G.Z. 
import xarray as xr
import logging
from pandas import *
from tabulate import tabulate

#---------------
# misc functions 
#---------------
def prob_norm(mean,sigma,val):
    """ calculates probability of a value given normal distribution"""
    """ assume Guassian cost function """
    """ cost= probability of outside the bounds"""
    """ 1.0 = default value """
    """ 0.0 = infinite departure!!!"""
    return 1.0-abs(stats.norm(mean,sigma).cdf(val)-0.5)*2.0

#-------------------------------
# single member's parameter list
#-------------------------------
class member(object):
    """A dictionary set of model parameters"""
    def __init__(self):
        """initialize each member to have an empty dictionary of parameter values"""
        """and very large negative fitness"""
        self.vals={}
        self.fitness=-1.e30 
        # 2023 M.G.Z 
        # Changed to very large positive number (we are now minimizing)
      #  self.fitness=1.e30
        #==========================================================
    def coldstart(self,pars,rmethod=1):
        for par in pars:
            # initialize with Normal distribution about default:
            if rmethod==0:
                if par["tol"]>0:
                    val=np.random.normal(par["default"],par["tol"])
                val=max(val,par["min"])
                val=min(val,par["max"])

             # initialize with uniform distribution between min/max
            if rmethod==1:

                val=np.random.uniform(par["min"],par["max"])

            self.vals[par["name"]]=val

    def mdeparture(self,pars,params):
        """member departure as log likihood"""
        #
        # Calculate a weighted departure cost
        # No longer need ad-hoc cost functions as now we use probabilities
        # Product of probabilities:
        depart=[]
        self.departure=1.0
        self.sigma=0.0
        for par in pars:
            if par["tol"]>0:
                if params["llog"]==True:
                    normal_p=np.log10(prob_norm(par["default"],par["tol"],self.vals[par["name"]]))
                    self.departure+=normal_p
                else: 
                    normal_p=prob_norm(par["default"],par["tol"],self.vals[par["name"]])
                    self.departure*=normal_p

                # ratio to sigma tolerance for graphical diagnostics
                self.sigma+=abs(self.vals[par["name"]]-par["default"])/par["tol"]

 
    def mfitness(self,params):
        """member fitness as log likihood"""
        #self.fitness=self.departure+self.stats[params["skill_indicator"]]
        # %%%HACK for SIT... sort out later 
        self.fitness=self.stats[params["skill_indicator"]]
        
    # mutate genetic information
    def mutate(self,pars,igen,params,rmethod=1):
        """mutate parameters for single member"""
        # scale down mutation magnitude as calibration progresses
        fac=np.exp(-float(igen)/float(params["mutate_tau"]))
        # start rate high but relax to long term rate...
        mfac =fac*params["mutate_fac0"] +(1.0-fac)*params["mutate_fac"]
        mrate=fac*params["mutate_rate0"]+(1.0-fac)*params["mutate_rate"]
        for par in pars:
            # doesn't mutate every step, there is a mrate probability of mutations:
            if (par["tol"]>0) and (np.random.uniform()<mrate):
                # This picks new genetic value from normal around current value
                if (rmethod==0): 
                    val=np.random.normal(self.vals[par["name"]],mfac*par["tol"])
                if (rmethod==1):
                    rmin=self.vals[par["name"]]-mfac*par["tol"]
                    rmax=self.vals[par["name"]]+mfac*par["tol"]
                    val=np.random.uniform(rmin,rmax)

                # make sure not out of range.
                val=max(val,par["min"])
                val=min(val,par["max"])
                #print ("***** mutate ",par["name"],self.vals[par["name"]],val)
                self.vals[par["name"]]=val

#-------------------------------------------
# ensemble class - whole ensemble of members
#-------------------------------------------
class ensemble:
    """an ensemble of members"""
    # each member has a vals dictionary, with name:number
    def __init__(self,size):
        self.mem=[] #empty list
        for imem in range(size):
            self.mem.append(member()) # append empty dictionary+fitness=very bad

    def coldstart(self,pars):
        for i in range(len(self.mem)):
            self.mem[i].coldstart(pars) # can also specify method

    def restart(self,pars,params):
        """ read in par vec from csv file and cycle to initialize first vec"""
        # open csv and read in par arrays:
        df=pd.read_csv("model_parameters_ens.csv")
        # safety if start-1>max in file, start is global so this is passed back
        istart=min(params["start"]-1,df['igen'].max())
        #
        # check that ALL pars are written to file (e.g. cpu limit didn't kick in)
        if len(df[df['igen']==istart])<len(pars):
            print ('WARNING, model pars file contains incomplete last generation=',istart)
            istart-=1  
        params["start"]=istart+1 # doesn't do anything unless previous line clips
        print("Reference generation for restart is ",istart)
        for par in pars:
            # pick out vector of values from the correct generation.
            print ("var search ",par["name"])
            parvec=ast.literal_eval(df.loc[(df.igen==istart)&(df.Name==par["name"])].vals.tolist()[0])
            lparvec=list(islice(cycle(parvec),len(self.mem)))
            for i in range(len(self.mem)):
                self.mem[i].vals[par["name"]]=lparvec[i]

    def departure(self,pars,params):  
        """creates the departure vector for the ensemble"""
        for imem in range(params["nens"]):
            self.mem[imem].mdeparture(pars,params)

    def fitness(self,params):
        """ calculate fitness for an ensemble"""  
        for imem in range(params["nens"]):
            self.mem[imem].mfitness(params)

    def append2(self,e1,e2):
        """appends two ens objects to new object self"""
        ne1,ne2=len(e1.mem),len(e2.mem)
        for i in range(ne1):
            self.mem[i]=deepcopy(e1.mem[i])
        for i in range(ne2):
            self.mem[i+ne1]=deepcopy(e2.mem[i])
            
    def statistics(self,pars,igen,params):
        """ calculate some ensemble mean statistics in dictionary"""
        """ this is done on the BEST vector """
        # 
        # this routine is horrible and needs generalizing:
        #

        estats={
          'mskill':np.mean([x.stats[params["skill_indicator"]] for x in self.mem]),
          'mbias':np.mean([x.stats["bias"] for x in self.mem]),
          'mrmse':np.mean([x.stats["rmse"] for x in self.mem]),
          'mdeparture':np.mean([x.departure for x in self.mem]),
          'msigma':np.mean([x.sigma for x in self.mem]),
          'mbpval':np.mean([x.stats["bpval"] for x in self.mem]),
          'mrval':np.mean([x.stats["rval"] for x in self.mem]),
          'mr2pval':np.mean([x.stats["r2pval"] for x in self.mem])
              }

        #========================================================
        writer.add_scalar('Fitness', estats["mskill"], igen)   # M.G.Z 2023
        writer.add_scalar('Parameter_departure', estats["msigma"], igen)
        #========================================================

        #store.append(list(estats.values()))
        store[igen-params["start"],:]=np.array(list(estats.values()))
        for par in pars:
            parvec=[]
            for imem in range(len(self.mem)):
                 parvec.append(self.mem[imem].vals[par["name"]])
            ensmean='%s' % float('%.6g' % np.mean(parvec))
            ensstd='%s' % float('%.6g' % np.std(parvec))
            ensmin='%s' % float('%.6g' % np.min(parvec))
            ensmax='%s' % float('%.6g' % np.max(parvec))
            #print(par["name"],ensmin,ensmean,ensmax,ensstd)
            params["parfile0"].writerow([igen,par["name"],parvec])
            params["parfile1"].writerow([par["name"],ensmean,ensstd,ensmin,ensmax])

        params["parfile0"].writerow([igen,"skill",[x.stats[params["skill_indicator"]] for x in self.mem]])                         

        return(estats)

    def generation(self,pars,best,params,igen):
        """creates a new generation based on a fitness metric"""
        """arguments are the parameter list and the best vector of best models"""
        """this routine also sorts a new vector of nbest models"""

        # new long vector
        all_ens=ensemble(params["nens"]+params["nbest"]) # set up clean long list 
        all_ens.append2(self,best) # create long list of best and ens models with deepcopy.

        # Now we put the nens+nbest models in a single list and pick out the nbest models.
        list_fitness=[x.fitness for x in all_ens.mem] # all member log likihoods, len=nens+nbest 
        idx=heapq.nlargest(params["nbest"],range(params["nens"]+params["nbest"]),list_fitness.__getitem__)
       # idx=heapq.nsmallest(params["nbest"],range(params["nens"]+params["nbest"]),list_fitness.__getitem__)
       # 2023 M.G.Z (minimizing rmse)

        # copy nbest best models to best vector
        for i in range(params["nbest"]):
            best.mem[i]=deepcopy(all_ens.mem[idx[i]])

        best_fitness=[x.fitness for x in best.mem] # best mem fitness

        # Pretty print table
        df=DataFrame({'skill':best_fitness})
        logging.info(f"========== the N best model fitness ========== \n{tabulate(df, headers='keys', tablefmt='mixed_outline')}") 
        logging.info("==============================================")
        # the fittest models in best are used for selection...
        max_fitness=max(list_fitness)
        min_rmse=min(list_fitness) # 2023 M.G.Z.

        # we want to keep the NKEEP best models for the next gen, without mutation!
        keep_if=sorted(list(enumerate(list_fitness)),key=lambda tup: tup[1])[-params["nkeep"]:]
     #   keep_if=sorted(list(enumerate(list_fitness)),key=lambda tup: tup[1])[:params["nkeep"]] # 2023 M.G.Z
        
     #   logging.info(f"============================== MIN rmse {min_rmse}") # 2023 M.G.Z.

        # now locate all "good" models that are within survive% likihood of MAX best model in the long list.
        # this might only be one model... which fitness genetic diversity, and thus high 
        # mutation is needed towards start, AND survival of fittest without mutation in mem0
        # eventually it might be all nbest models...
        
        list_fitness=np.array(list_fitness)

        if params["llog"]:
            good_mod_idx=np.argwhere(list_fitness>max_fitness+params["survive"]) # RECALL, log10 space.
        else:
         #   good_mod_idx=np.argwhere(list_fitness<150)
            good_mod_idx=np.argwhere(list_fitness>0.0)
                                            #   |<--->| 2023 M.G.Z
        n_good_mod=len(good_mod_idx)

        logging.info(f"{n_good_mod} good models found within survive fraction") 

        # create list of probability.  Convert pval from log space to real space.
        # probvec has <= than nens members recall
        # previously in nens, NOW over good models only:
        # adjustment by best fitness superfluous but avoids underflow
        probvec=[]
        for imem in good_mod_idx: 
            if params["llog"]:
                probvec.append(10**(list_fitness[imem[0]]-max_fitness)) 
            else:
                probvec.append(list_fitness[imem[0]]) 

        print ("RMSE ********************************* ",probvec)

        # CDF calculated  
        probvec=np.cumsum(probvec,dtype=np.float16)

        print("Cumsum(RMSE) ************************", probvec)
        if probvec[-1]<=0.0: 
            # set to equal probabilities and hope mutation saves you
            # this should NEVER happen unless you get underflow
            print ("SERIOUS underflow issues, switching to equal probs")
            probvec=(np.arange(params["nens"])+1.0)/float(params["nens"])

        # choose parameters for the new generation.
        # need to do in two steps as some parents have several children
        ran_genes=np.random.uniform(high=probvec[-1],size=(params["nens"],params["nparent"])) # this is the selection vector

        # Series of integers to select parents
        # e.g. for 2 parents will be like 0 0 1 0 1 1 1 0 etc... meaning it selects
        # integers from 0-1. Each parameter for each ensemble gets a parent.
        # bug corrected, now have a different combination for each member 
        ran_pars=np.random.randint(params["nparent"],size=(params["nens"],len(pars)))

        # need nens empty dictionaries here for new generation
        # newvals=[dict() for x in range(params["nens"])]

        # now choose the parents for the nens members for nens-nkeep members:
        for imem in range(params["nkeep"]):
            parent=keep_if[imem][0] # index of i_th best model
            for par in pars:
                self.mem[imem].vals[par["name"]]=copy(all_ens.mem[parent].vals[par["name"]])

        # the rest chosen at random from parents
        for imem in range(params["nkeep"],params["nens"]):
            # separate parent for each member - if nparents=1 then all from same parent
            for ipar,par in enumerate(pars):
                # note that we now select from GOOD models only:
                parent=good_mod_idx[bisect(probvec,ran_genes[imem,ran_pars[imem,ipar]])][0]
                self.mem[imem].vals[par["name"]]=copy(all_ens.mem[parent].vals[par["name"]])
                # print(par["name"],' from ',parent)

    def mutate(self,pars,igen,params):
        """mutate the ensemble"""
        # NOTE: nkeep fittest are not subject to mutation
        # but their children may be:
        for imem in range(params["nkeep"],params["nens"]):
            self.mem[imem].mutate(pars,igen,params)
    
def getpars(file):
    """ generate list of dictionaries for the parameters"""
    pars=[]
    reader=csv.reader(open(file),delimiter=',')  
    
    # get keys stripping spaces from names
    keys=[x.strip(' ') for x in next(reader)]

    # now read entries and append the dictionary
    for row in reader:
        # strip spaces and then convert all numbers to floats.
        values=list(list2flt([x.strip(' ') for x in row]))
        pars_entry=dict(zip(keys,values))
        pars.append(pars_entry) # append the dictionary entry
        
    return(pars)


#----------------------------------
# python code for genetic algorithm
# A. Tompkins 2015
#----------------------------------
def list2flt(seq):
        for x in seq:
            try:
                yield float(x)
            except ValueError:
                yield x

#----------------
# MAIN CODE START
#----------------
def main(params):
    """main routine to calibrate any nonlinear model"""

    # A vector of nens models is made each generation using cross over and mutation
    # Selection of parameters made according to parent's fitness (nparents)
    # fitness is a combination of maximum skill and minimum parameter departures (set prior)
    # At each generation the nbest models are remembered in a separate vector
    #
    # The base method is described in Tompkins and Thomson, 2018, PLOS1, 
    #

    # need to generalize to allow calibration as a function of lat/lon...
    #
    import os, sys
    
    #calibration=open('calibration.txt','w')
    #logging.basicConfig(stream=calibration, level=logging.INFO)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    
    # "stream" selects the output channel for the logging messages,
    # i.e., either stdout, stderr or some object that allows to write()
    # on it.
    sys.path.insert(1,os.environ['VECTRI']+"/calibration/")
    # import vectri_sit as model
    # import lorenz as model
    import vectri_eggs as model
  #  from tensor_to_csv import tflog2pandas as to_csv
    
    ncore=int(multiprocessing.cpu_count())
    #
    # 0. Get arguments
    #

    #
    # 1. initialize model settings and diag files
    #
    #===========================================================================================#
    # 2023 M.G.Z
    data_loc=str(params["data_loc"][0]) 
    #data_obs=str(params["data_obs"][0])
    ivec    =params["x"]

    #===========================================================================================#
    #
    np.random.seed() # place a fixed number in brackets for reproducable results
    iparfile=model.init()
    print(iparfile)

    # 2. define params and their bounds and apply safety to various parameters.
    pars=getpars(iparfile)
    npars=len(pars)
    params["nparent"]=npars if params["nparent"]==0 else min(params["nparent"],npars)
    params["nbest"]=min(params["nbest"],params["nens"]) # safety for nbest which must be < nens
    if ncore<=1 or params["nens"]==1:
        params["lparallel"]=False   # switch to serial if 1 core selected.
    ncore=min(ncore,int(multiprocessing.cpu_count())) # not more than available on machine

    print("***parameters for run***")
    print("nens=",params["nens"]," ngen=",params["ngen"]," nparent=",params["nparent"],"start gen=",params["start"], 
          "ncore=",ncore,"nbest=",params["nbest"],"skill metric=",params["skill_indicator"],"initerr=",params["initerr"],
          "skill file",params["skill_file"])
    
    # 3. initialize the ensemble, or read in from previous run
    ens=ensemble(params["nens"])   # set up ensemble vector of nens members
    best=ensemble(params["nbest"])  # set up initialized vector of nbest best members

    if params["start"]==0:
        ens.coldstart(pars)
        params["parfile0"]=csv.writer(open("model_parameters_ens.csv", "w"))
        params["parfile0"].writerow(["igen","Name","vals"])
    else:
        ens.restart(pars,params)
        params["parfile0"]=csv.writer(open("model_parameters_ens.csv", "a"))        
        print("new value of start",params["start"])

    # write file parameters to a csv file - APPEND if restart
    params["parfile1"]=csv.writer(open("model_parameters_stat.csv", "w"))
    params["parfile1"].writerow(["Name","ens mean","ens stddev","min","max"])

    #  hardwire the store size to the number of variable desired:
    #  need to rewrite to automatically detect size needed:
    global store
    store=np.zeros((params["ngen"],8)) # THIS IS HARDWIRED THE DIAGNOSTICS ARRAY SIZE... 
    
    # loop here over generations:
    for igen in range(params["start"],params["ngen"]+params["start"]):

    # 4. Run the model member and calculate its skill
        logging.info("====================================")
        logging.info(f"Running model generation {igen:.0f}")
        logging.info("====================================")

        # mlab is used in the model run output file.
        #  - set to igen to keep the output from each generation
        #  - set to a constant value or empty string if you want to overwrite each generation
        #mlab=0
        mlab=0

        t0 = time.time()
        # Parallel processing if lparallel=True, note that unfortunately only ONE NODE allowed (shared memory)
        # even if this particular instance of vectri requires no communication - will move to celery later.
        if params["lparallel"]:

            print('.run')
            pool=multiprocessing.Pool(processes=ncore)
            pool.starmap(model.run,([imem,mlab,ens.mem[imem].vals,ivec,data_loc] for imem in range(params["nens"]))) # initerr
            pool.close()
            pool.join()
            pool=multiprocessing.Pool(processes=ncore)
            stats=pool.starmap(model.skill_map,([imem,mlab,ens.mem[imem].vals] for imem in range(params["nens"]))) 
            pool.close()
            pool.join()

            # assign vector of dictionary to ensemble structure
            for imem in range(params["nens"]):
                ens.mem[imem].stats=copy(stats[imem])
        else: # serial processing
            for imem in range(params["nens"]):
                model.run(imem,mlab,ens.mem[imem].vals,ivec,data_loc)
                ens.mem[imem].stats=model.skill_map(imem,mlab,ens.mem[imem].vals)
                print("PARENT:",imem,' ; rmse:',ens.mem[imem].stats['rmse'],'\n',ens.mem[imem].vals)

        t1 = time.time()
        logging.info(f"===================== iteration time = {(t1-t0)/60:.2f} minutes =====================")
       
        # 5. Ensemble parameter departure and fitness function
        
        ens.departure(pars,params)

        ens.fitness(params)

     #   print("fitness vec",ens)
        
        # 7. Create new generation, and filter out nbest models to BEST vector
        ens.generation(pars,best,params,igen) 

        # 6. Calculate some ensemble mean statistics and store to file - BEST vector
        best.statistics(pars,igen,params)  
    
        # 8. mutate the parameters
        ens.mutate(pars,igen,params) 
        
    #
    # final output here
    #    
    # Ratio SD/TOL gives our knowledge estimate:

    logging.info("************************")
  #  logging.info(f"    RUN FINISHED after {params["ngen"]} generations")
    logging.info(f"    RUN FINISHED ")
    logging.info("************************")
    logging.info(f"npars= {npars}")
    
    skillfile = csv.writer(open("final_skill.csv", "w"))
    skillfile.writerow(["skill indicator is ",params["skill_indicator"]])
    skillfile.writerow(["mem",best.mem[0].stats.keys(),"departure","fitness"])
    for imem in range(params["nbest"]):
        #skillfile.writerow([imem,best.mem[imem].stats[params["skill_indicator"]],best.mem[imem].stats["bias"]])
        skillfile.writerow([imem,best.mem[imem].stats.values(),best.mem[imem].departure,best.mem[imem].fitness])

    # write file parameters of BEST vector to a csv file
    parfile=csv.writer(open("final_parameters.csv", "w"))
    parfile.writerow(["Name","default","tol","min","max","ens mean","ens stddev","member values"])

    # ensemble mean diagnostics for model parameters
    for par in pars:
        parvec=[]
        for imem in range(params["nbest"]):
            parvec.append(best.mem[imem].vals[par["name"]])
        ensmean='%s' % float('%.6g' % np.mean(parvec))
        ensstd='%s' % float('%.6g' % np.std(parvec))
        parfile.writerow([par["name"],par["default"],par["tol"],par["min"],par["max"],ensmean,ensstd,parvec])

    # write store to json file: 
    json.dump(store.tolist(), codecs.open('skill_series.json', 'w', encoding='utf-8'),
        separators=(',', ':'),sort_keys=True, indent=4)    

    # write a set of VECTRI.options files to use in model runs.
    # MOVE to vectri.py
    for imem in range(params["nbest"]): 
        options_f=open("vectri_mem"+str(imem)+".options", "w")
        for par in pars:
            options_f.write(par["name"]+"="+str(best.mem[imem].vals[par["name"]])+"\n")
        options_f.close()
        


def defaults():
    params={}
    params["mutate_rate0"]=0.5 # initial probability of gene mutation
    params["mutate_rate"]=0.02  # long term probability of gene mutation
    params["mutate_fac0"]=1.0   # initial ratio of tolerance to scale random perturbation
    params["mutate_fac"]=0.1    # ratio of tolerance by which to scale random perturbation
    params["mutate_tau"]=15     # E-folding number of generations to decay mutate_fac AND rate towards final.

    params["survive"]=-3.0 # np.log10(0.001)  # log10(fraction) of best model probability that a member needs to survive.

    # i.e. log10(0.01) means model needs to be at least 1% as likely as best model to survive
    params["nens"]=80          # number of ensemble members for mixing, larger the better for sampling.
    params["nbest"]=10         # final ensemble size of good models
    params["ngen"]=40          # maximum number of generations allowed
    params["start"]=0          # starting generation (zero for cold start, or >0 for restart from csv best vector file
    params["nparent"]=2        # number of parents - if ZERO then is reset to nparams which is also max.
    #obssigma=0.2     # standard deviation of observation error
    params["nkeep"]=1          # nkeep models are guaranteed to survive to next generation without mutation 
    params["initerr"]=0.0      # sigma on initial condition error
    params["skill_indicator"]="rmse" # r2pval,bpval, [rmse,bias need mods]...
    params["skill_file"]="not_operational"
    params["llog"]=False       # set to true if working in probability space to prevent underflow.
    params["lparallel"]=False  # run model and stats in parallel, those are the heavy bits. 
    #===========================================================================================#
    params["x"]=10                                      # 2023 M.G.Z - Mosquito scheme (default: 10=Aedes)
    params["data_loc"]=os.environ['VECTRI']+"/../data"  #            - path to the folder of the data that drives the model (if any)
    params["data_obs"]=os.environ['VECTRI']+"/../data/eggs.nc"  #    - path to the file with the data set used to calibrate the model
    #===========================================================================================#
    return params

def call_example():                                                                                                                            #|<-------- 2023 M.G.Z ----------------->|
    callexample='genetic.py --nens=I --nparent=J --ngen=K --nbest=L --ncore=N --start=S --skill skill-metric (bpval [default],r2pval) --error=F --x=ivec --data_obs=path/file_obs --data_loc=path'
    print (callexample)
    print("I=number of model ensemble members")
    print("I=number of model ensemble members")
    print("J=number of parents in cross over (if 0 then J=K)")
    print("K=number of generations (fixed at the moment)")
    print("L=number of best model members require (final parameter sets)")
    print("S=start generation, 0(default)=cold start with random vector >0 restart from model_parameters_ens.csv file gen=S)")
    print("N=number of cores for parallel execution (default=max on computer [node]), 1=serial ]")
    print("F=inital condition error")
    print("G=tells the model which generation to start from ")
    #===========================================================================================#
    # 2023 M.G.Z
    print("ivec     = integer number that selects the mosquito scheme --> 10:Aedes Albopictus, 0:Anopheles Gambiae")
    print("data_obs = path and filename of the validation dataset used in your skill metric") 
    print("data_loc = path to input driving the model") 
    #===========================================================================================#
if __name__ == "__main__":
    import os,sys
   # set_start_method('forkserver', force=True)
    vdir=os.environ['VECTRI']
    sys.path.insert(1, vdir+"/utils/")
    print (vdir+"/calibration/")
    from getargs import getargs
    params=defaults() 
    params=getargs(params)
    writer = SummaryWriter()
    main(params)
    writer.close()
    
 #   path="runs/Run1" #folderpath
 #   df=tflog2pandas(path)
#df=df[(df.metric != 'params/lr')&(df.metric != 'params/mm')&(df.metric != 'train/loss')] #delete the mentioned rows
 #   df.to_csv("output.csv")

