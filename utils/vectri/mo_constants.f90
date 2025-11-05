MODULE mo_constants

  !--------------------------------------------------------------------------------
  ! VECTRI: VECtor borne disease infection model of TRIeste.  
  !
  ! Tompkins AM. 2011, ICTP
  ! tompkins@ictp.it
  !
  ! tunable constants for model
  ! 

  ! updates: v1.4.0 Added immunity
  !          v2.0   Added multiple vectors
  !                 Added interventions
  !
  ! note: for improved compatibility with machine learning, should read in defaults
  !--------------------------------------------------------------------------------

  IMPLICIT NONE

  !
  ! GENERIC DEFAULT VALUES FOR ALL VECTORS - THESE ARE THEN OVERWRITTEN BELOW IN THE CASE STATEMENT 
  ! THE GENERIC DEFAULT VALUES ARE FROM THE ORIGINAL V1.9 MODEL FOR GAMBIAE+MALARIA FALCIPARUM
  !

  ! From v1.11.0
  ! Vector index for specific defaults
  ! 0: Anopheles Gambiae
  ! 1: Anopheles Funestus (not evaluated)
  ! 2: Anopheles Sacharovi 
  ! 10: Aedes Albopictus
  ! 11: Aedes Agypti (not evaluated)
  ! 20: Culex Pipiens (not available yet)  
  INTEGER :: ivec=0

  ! From v1.11.0
  ! Disease index for specific defaults
  ! -1: OFF
  !  0: Plas. Falciparum
  !  1: Plas. Vivax (not operational)
  ! 10: Dengue (not operational)
  INTEGER :: idisease
  
  ! We may adapt this whole block to Fortran TYPES in v2.* but
  ! need to work out how to handle namelist (or replace)
  ! This will probably happen when the bash wrapper is replaced by
  ! a python-based interface, possibly v3.0
  CHARACTER(LEN=100)  :: vector_name, disease_name

  ! -----------------
! Surface Hydrology 
! -----------------
! 0: Externally provided pond fraction from datafile (from v1.8.4)
! 1: default (v1.2.6) described in Tompkins and Ermert, Mal. J. (2013)
! 2: Revised scheme described in Asare et al. 2016a,b (Geospatial Health and PLOS1)
  INTEGER :: npud_scheme=0
! IMPORTANT NOTE: if external data not found reverts this option as default
  INTEGER :: npud_scheme_default=2 ! if external data is missing, specify the default option

!
! Larvae scheme 
!   1: constant as in Ermert 2010
!   2: Jepson 1947 as reported by HM04
!   3: BL2003 (approximated linearly)
!   4: Craig et al. (1999) - close to BL2003
!
  INTEGER :: nlarv_scheme=4

  ! vector temperature dependent survival scheme in use (see Emert PhD 2010)
  ! 1= MartinsI
  ! 2= MartinsII
  ! 3= Bayoh
  ! 4= ???
  INTEGER :: nsurvival_scheme


  INTEGER :: nsporo_scheme
  ! Sporogonic cycle scheme in use
  ! 1= Detinova (1962) ; Anopheles gambiae ; Degree-day:  [ref]
  ! 2= ??              ; Aedes albopictus  ; Exponential: [ref]
  ! 3= ??              ; Aede aegypti      ;   "     "  : [ref]

  
  ! 1: This is a constant rate - Temperature *INdependent* - 12 days 
  REAL :: rlarv_ermert  ! units day**-1 
 
  ! 2: Jepson 1948 cited (not used?) in HM04 - T-dependent rate
  REAL :: rlarv_jepson  ! units K**-1 day**-1 

  ! 3: from Bayoh and Lindsay 2003, (see p76 Ermert2010)
  ! the BL2003 paper uses an exponential function with very large factors
  ! we approximate this with a linear function
  REAL :: rlarv_bayoh ! units K**-1 day**-1 

  ! 4: From Craig et al 1999 - this approximates Bayoh very closely [CITATION]
  REAL :: rlarv_craig !  units K**-1 day**-1  degree day constant for growth rate

  ! rate constants for larvae maturation, array for convenience.
  REAL, DIMENSION (4,2) :: rlarvmature

  ! TYPE c_vec ::
  !
  ! larvae stage constants
  ! ----------------------
  ! Number of eggs per batch LEADING TO FEMALES (i.e. total batch*female ratio ~0.5)
  REAL :: neggmn    
   
  ! max and min temperature outside of which no larvae survive (c) from Bayoh and Lindsay (2004)
  ! need to combine with ***death rate*** - NOTE COMPATIBLE WITH SCHEME
  REAL :: rlarv_eggtime   ! days for egg hatching
  REAL :: rlarv_pupaetime ! days for pupae stage

  ! vector survival constants
  ! maximum temperature Jepson et al., 1947; Depinay et al., 2004 as stated in Bomblies 2008
  ! REAL :: rtlarsurvmax=40.0 ! maximum temperature (C) above which larvae dies
  
  ! The rflushmin parameter is set to the SURVIVAL average of L1 to L4 larvae
  ! according to Krijn P. Paaijmans1,2*, Moses O. Wandago2, Andrew K. Githeko3, Willem Takken (2007)
  ! 0.89 = L1 larvae flushed out at 17.5% rate after heavy rainfall, L4 at 4.8%... 
  REAL :: rlarv_flushmin ! minimum survivial with high rate 
  REAL :: rlarv_flushtau   ! (mm/day) describes how flushing increases with rainrate 

  ! Larvae growth rate scheme 
  !   1: constant as in Ermert 2010
  !   2: DD - Jepson 1947 as reported by HM04
  !   3: DD - BL2003 (approximated linearly)
  !   4: DD - Craig et al. 1999 

  !
  ! slope and offsets for larvae schemes - Set by nlarv_scheme in mo_control
  !
  REAL :: rlarv_tmin  ! 16 old constant - BL=18 slope of parameterization for fractional growth
  REAL :: rlarv_tmax  ! 37 BL=34 

  ! larval mass and ecocapacity constants - taken from Bomblies et al. 2009, we assume linear growth
  REAL :: rmasslarv_stage4    ! mass in mg of stage 4 adult 
  REAL :: rbiocapacity       ! max bio carry capacity of 1m**2 of pool. 

  ! base daily survival  due to preditors and real life (non-lab) factors
  ! before v1.2.9 was fixed to 0.825 
  !   HM04 and Bomblies use 0.88, Ermert 2010 uses 0.825  
  ! After v1.3.0 this base rate is further reduced by Temperature-dependent
  ! Craig et al 1999/Bayoh and Lindsay 2004 
  ! All versions then reduced this further for earlier stage larvae (linear) for flushing effect.
  REAL :: rlarvsurv  ! The new parametrization fits with 0.987 to Craig/Bayoh data combined 

  ! from v2.0 these are introduced to allow different water behavior of vectors - note below
  ! by using these fractional rates we can model the different water behaviour of different vectors. 
  REAL :: wpond_ratio  ! ratio of temporary ponds selected by vector 
  REAL :: wperm_ratio  ! ratio of permanent features, higher for anoph. funestus 
  REAL :: wurbn_ratio  ! ratio of urban sites (gutters, tires etc),
                       ! higher for Aedes aegypti and albopictus and also anoph. Stephensi

  ! proportion of time spent indoor resting 
  REAL :: rbeta_indoor

  !
  ! biting parameters
  ! -----------------
  ! daily bite rate of vectors to initiate gonotropic cycle
  ! this fraction manage to locate a host and get a meal each day! 
  ! CITATION REQUIRED
  REAL :: rbiteratio             ! Success rate of finding a blood meal per day 
  REAL :: rzoophilic_tau         ! e-folding rate for zoophilicity (people/km**2) 
  REAL :: rzoophilic_min         ! minimum rate for low population densities 
                                 ! (rate lower since adjust to feed on cattle) 
  REAL :: rbite_night            ! ratio of bites taken during sleeping hours (only used for bednets)

  ! vector mortality functions
  REAL :: rvecsurv ! underlying survival on which temperature based function is imposed.
  REAL :: rvecsurv_min

  ! Diffusion coefficient for vector movement from cell to cell
  ! if time step is in units of days, then this has units KM**2/day
  ! thus if a flight path is order of 1km for daily search then this is 1.0 
  ! suggested value is around 0.1-0.3 km**2/day, estimated from Thomas et al plos 1 2013
  REAL :: rvect_diffusion   ! 0.25 is a reasonable value
  
  ! TYPE c_wperm
  ! default water fraction of permanent water bodies used if
  ! Sentinel maps are not read in, and also used as minimum if > sentinel
  ! otherwise wperm set to this everywhere
  REAL :: wperm_default 

  ! END TYPE c_wperm
 
  ! TYPE c_wpond 
  REAL :: wpond_evap       ! evaporation rate in mm/day (*Lv/86400 gives units of Wm^-2) 1.728=50w/m2
  REAL :: wpond_max      ! max default water fraction def=0.2 - also used in v130

  ! infiltration rates using the GLDAS soil texture map:
  ! default values from Annex 2 of FAO soil management training methods : 
  ! https://www.fao.org/3/S8684E/S8684E00.htm
  ! units are mm/day (*Lv/86400 gives units of Wm^-2)  e.g. ! 1.728=50W/m2
  ! If no soil map is provided then all cells are set to mean of these three values.
  REAL :: wpond_infil_clay
  REAL :: wpond_infil_silt
  REAL :: wpond_infil_sand

  ! constants specific for npud_vers=1
  REAL :: wpond_rate      ! increase rate (m^-1)

  ! constants specific for npud_vers=2 (Asare et al. 2016a,b)
  REAL :: wpond_CN        ! 25400/CN-254 curve number 85 (range 80 - 90)
  REAL :: wpond_min       ! min default water fraction
  REAL :: wpond_shapep2   ! shape factor p DIVIDED BY 2 (default p=1, range=0.5-2.0)
  REAL :: wpond_S         ! =25400/rwaterfrac_CN-254 - defined in setup
  REAL :: wpond_ia        ! from v1.3.5 initial abstraction (0.05-0.2)
  REAL :: wpond_depthref  ! reference water depth (default=300 mm, range=250-350)
  REAL :: wpond_ref       ! reference water fraction (default=10%*rwaterfrac_max, range=0.5% - 2%)

  REAL :: wurbn_tau       ! people per km**2 tau log function
  REAL :: wurbn_sf        ! scale factor for urban function
  
  ! offset of water temperature to air temperature
  REAL :: rwater_tempoffset  
  
  ! END TYPE c_wpond
 
  !------------------------
  ! Intervention strategies
  !------------------------
  !
  ! 1. BEDNETS
  !    Bednets distributions are read in from the data file
  !    The number of bednets are read in, and the model uses the population density
  !    to convert this to the proportion of people that sleep under a net using a random overlap assumption
  !    All nets are assumed treated, they lose this treatment 
  !
  ! We assume all nets are LLINs
  !
  ! ~ 3 years: Pulkki-Brännström Cost Effectiveness and Resource Allocation volume 10, Article number: 5 (2012)
  ! 2-4 years: Solmon et al Malaria Journal volume 17, Article number: 239 (2018)
  ! The solmon paper shows in fact that the insecticide actually outlasts the physical integrity of the net
  ! and Pulkki-Brannstrom show at least the two are ~, which simplifies matters as the model can assume all
  ! nets in the field are effective in terms of the insecticide until no longer useable.
  ! see also
  ! Haji et al Malaria Journal volume 19, Article number: 187 (2020)
  ! Mansiangi et al Malaria Journal volume 19, Article number: 189 (2020)
  ! Obi et al Malaria Journal volume 19, Article number: 124 (2020)
  ! These papers show similar values but with lot of variation from location to location
  !
  ! from all these we are going to assume a median bednet lifetime of t_median = 2 years, which means
  ! tau defaults to -t_med/ln(0.5) = 1.44 * t_med
  REAL :: rbednet_tau ! days, efolding time for nets

  ! 2. SIT - Steralized Insect Technique
  !
  !          This is also read in from the external data file, treated male vector dens
  !          Models assumes
  !          1. Treated males are homogeneously mixed within population,
  !          2. Treated males are less competitive at breeding by a factor rsit_breed
  !          3. Treated males have higher mortality, their survival rate reduced by fac rsit_surv
  !          4. Females breed just once, and if with SITm all their eggs are non-viable. 
  !
  ! This is from ! Gato et al. 10.3390/insects12050469   = 0.56
  REAL :: rsit_breed
  
  ! NOTE: How much more likely radiated adults are to die
  ! Bond et al. PLOS 1 2019 https://doi.org/10.1371/journal.pone.0212520 - approx 2 
  REAL :: rsit_mortality  

  ! Distribution of bites in the post v1.3.5 version: rbitehighrisk is a factor between 1.0 and infinity...
  !
  ! rbitehighrisk: the ratio of risk between the higher vulnerable population (in the EI category) and the 
  !                lower vulnerable population (the susceptibles S).  Until we get an agent based approach, 
  !                we used prior bite history as a proxy for vilnerability in this way.
  ! Thus if b is the mean bites per person, k the factor below, bs bites per person in non-vulnerable S group
  ! b= pr k bs + (1-pr) bs, thus bs=b/(1+(k-1)pr)
  !   
  ! Within each categories the bite distribution is still distributed randomly, but the overall distribution of 
  ! bites per person across the population will have a wider distribution.
  !
  ! Setting rbitehighrisk=1.0: no difference in risk, this reproduces the default model prior to v.1.3.5
  ! 
  REAL :: rbitehighrisk=5.0 ! 1.0 no effect, >1.0 those already infected are assumed to be at high risk - 

  ! ---------------------------
  ! GARKI type model parameters
  ! ---------------------------
  ! This has to be defined here for dependencies
  ! v.1.4.0 DO NOT CHANGE FROM
  ! 1. Further age categories will be introduced with v2.X 
  INTEGER, PARAMETER :: nhost=1    ! number of host categories in garki type model

  ! TYPE c_disease
       
  ! number of days after infection for clearance of disease in non-immune subjects
  ! This is very difficult, as it depends on seeking of treatment 
  ! 
  ! Roe et al 2022 https://doi.org/10.1016/j.pt.2022.02.005 
  ! show fast natural clearance of O(4-10 days) in highly immune adults, longer in child
  !
  ! Felger, Ingrid, et al. "The dynamics of natural Plasmodium falciparum infections." (2012): e45542.
  ! show clearance rates on order 50-100 days in review 
  !
  ! but symptomatic cases may be cleared very quickly if treatment is sought 
  ! McCombie, Susan C. "Treatment seeking for malaria: a review of recent research." 
  ! Social science & medicine 43.6 (1996): 933-945.
  ! This is somewhat out of date but shows majority of cases are treated even in 90s.
  !
  ! Thus treatment means a shorter clearance is required: treatment is sought for most clinical cases
  ! With treatment clearance times are on the order of 2-14 days
  !  e.g. Brandts, Christian H., et al. "Effect of paracetamol on parasite clearance time in 
  !  Plasmodium falciparum malaria." The Lancet 350.9079 (1997): 704-709.)
  ! although it is assumed that it may take several days before treatment is sought.
  !
  ! SOLUTION: as well as dividing hosts into immune and non-immune, we also need to have classes
  !           of those who seek treatment and those who do not.  However it is likely we will need 
  !           to tackle this after we move to an agent-based paradigm for the host w coupling 
  !           to the WISDOM model, as this will also allow for other factorisation (age/wealth etc) 
  !           as well as comorbidity.
  !
  !
  ! from v1.8 natural clearing is added to the immune category:
  ! 
  ! In contrast to the above citations, there is some evidence for much longer clearance in immune categories:
  ! 
  ! Klein, E.Y., Smith, D.L., Boni, M.F. and Laxminarayan, R., 2008. 
  ! "Clinically immune hosts as a refuge for drug-sensitive malaria parasites". Malaria Journal, 7(1), p.67.
  ! which is 165/0.8
  ! 
  ! However this can be up to 13 years, see review of: 
  ! Ashley and White, The duration of Plasmodium falciparum infections
  ! Malar J. 2014; 13: 500.
  !. doi: 10.1186/1475-2875-13-500
  !
  ! This   
  REAL :: rhostclear       ! non-immune
  REAL :: rhostimmuneclear  ! immune class

  ! malaria transmission probabilities
  !   - these can be from 0.1 to 0.6 - depends on the immunity of the host
  !   - this will be generalized once the garki model is added and will be a function of host category
  REAL :: rpthost2vect_I   ! I: Infectious (nonimmune)
  REAL :: rpthost2vect_R  ! R: Recovered  (immune)

  ! prob of vector to host:
  REAL :: rptvect2host

  ! Immunity module - Very simple single compartment immunity treatment to extend model from SEI to SEIR1R2
  ! 
  ! R1=immune+parasite
  ! R2=immune clear
  ! from 1.11.0 R2->R1 added (EIR) and 
  ! loss of immunity only occurs from class R2
  !
  ! So model for humans is a SE...EIR model, with n bins for E to get delay for clinical onset
  ! The assumption is that 95% of the population gets full immunity thus EXP(EIRa/TAU)=0.05
  ! The default assumes that an annual EIRa of 100 bites 
  !   is adequate for complete (=95%) immunity following (PAPER HERE)
  ! Thus TAU=-100/ln(0.05)=33.4  - if we use this on daily step the
  !   model is timestep independent as exp(-eir/(n*tau))^n = exp(-eir/tau)
  ! Set to ZERO to switch off immunity.
  REAL :: rimmune_gain_eira ! default 100 - units EIR   [ -100.0/log(0.05) ]

  ! loss of immunity 
  ! tau set is set so that 95% of people lose immunity after X years.
  ! tau= -X*365/ln(0.05), so 365 gives 3 years loss...
  REAL :: rimmune_loss_tau  ! units days

  !
  ! vector parasite development constants - Detinova (1962)
  !
  ! Gonotropic cycle
  REAL :: rtgono ! threshold temperature for egg development in vector
                  ! Detinova (1962) gives 4.5 9.9 and 7.7 at RH=30-40,70-80 and 90-100
                  ! this will be implemented in an interpolation scheme
  REAL :: dgono
                  ! Detinova (1962) gives 65.4,36.5,37.1 at RH=30-40,70-80 and 90-100
                  ! this will be implemented in an interpolation scheme

  REAL :: aovi ! for GA calibration against egg data (scale factor)

  ! Sporogonic cycle from Detinova (1962) - 18.0 used by HM04, 16.0 by Ermert
  REAL :: rtsporo ! threshold temperature for parasite development
  REAL :: dsporo=111.0

  ! number of days MINUS ONE! after biting before a human becomes infective 
  ! 20 days in the LMM2010 - reference Ermert2011a and references therein - range 10-26d
  ! *NOTE* this has to be a parameter as it is used in mo_control to set a dimension
  !        bizarrely this produces a segmentation fault in the compiler if you make a var
  REAL, PARAMETER :: rhost_infectd=20.0


  ! day number MINUS ONE at which malaria can be detected by blood tests
  REAL, PARAMETER :: rhost_detectd=9.0   

  ! END TYPE c_disease
 
  ! constants for martins schemes, indices are powers of T:
  REAL, PARAMETER :: rmar1(0:2)=(/0.45, 0.054, -0.0016/)   ! martins I
  REAL, PARAMETER :: rmar2(0:2)=(/-4.4, 1.31,  -0.03/)     ! martins II (used in Craig et al. 99)

  ! make sure these are consistent with Martin's functions
  REAL, PARAMETER :: rtvecsurvmin=5.0  ! minimum temperature (C) below which vector dies
  REAL, PARAMETER :: rtvecsurvmax=39.9 ! maximum temperature (C) above which vector dies

  ! ------------------------------------------
  ! garki model constants for host development (currently inactive)
  ! ------------------------------------------
  ! adult/child indices, ni=non-imume, im=imune
  INTEGER, PARAMETER :: nadult_ni=1, nchild_ni=2, nadult_im=3, nchild_im=4


  ! MOVE this to initialization ?
  REAL :: rhost_infect_init=0.1  ! initial value of host reservoir

  !---------------------
  ! population constants
  !---------------------
  ! Death rate - Units fraction per year (translated later)
  ! This simply causes the death of this frac of the population, who are replaced by malaria naive 
  REAL :: rpop_death_rate=0.02  

  ! minimum population density (per km**2, i.e. km-2) allowed in calculation of HBR
  ! if population is below this count then assumed biting on other mammals, otherwise HBR is too high
  ! in very sparse populations 
  REAL :: rpopdensity_min

  ! migration level as fraction of population arriving per year with malaria infection
  ! at the moment this is treated as a simple minimum threshold
  REAL :: rmigration=1.e-5 ! one in a 100,000 people imported cases trickle ONLY when S<this level

  ! latitude limits 
  REAL :: rlatmax=75. ! turn the model off outside this limit for efficiency (assume malaria free)

  ! quality control parameters
  REAL :: rqualtemp_min=10.0
  REAL :: rqualtemp_max=50.0

  ! math constants
  REAL, PARAMETER :: rpi=ACOS(-1.0)     ! pi
  REAL, PARAMETER :: reps=1.0e-10       ! small positive threshold number
  REAL, PARAMETER :: r0CtoK=273.15      ! freezing point in Kelvin
  ! OUTPUTS:
  
! control of output file - default values.
! All of these are now in separate netcdf4 groups in hierachical structure
! Use NCO to flatten to netcdf3 if required: 
!    ncks -3 in.nc out.nc # Up to 2 GB Max variable size
!    ncks -6 in.nc out.nc # Up to 4 GB Max variable size
!    ncks -5 in.nc out.nc # No limit on variable size

! defaults

! Models Inputs:
  LOGICAL :: loutput_population=.false.   ! population
  LOGICAL :: loutput_soilinfil=.false.   ! infiltration rates
  LOGICAL :: loutput_wperm=.false.        ! output wperm fraction
  LOGICAL :: loutput_wpond=.true.        ! output pond water fraction
  LOGICAL :: loutput_wurbn=.true.        ! output urbn water fraction
  LOGICAL :: loutput_rain=.false.         ! precipitation
  LOGICAL :: loutput_t2m=.false.          ! 2 metre temperature

! Vector statistics
  LOGICAL :: loutput_vector=.true.       ! vector density
  LOGICAL :: loutput_larvae=.false.      ! larvae density 
  LOGICAL :: loutput_lbiomass=.false.    ! larvae biomass
  LOGICAL :: loutput_egg=.true.         ! rate of laying of new eggs
  LOGICAL :: loutput_emergence=.false.   ! Emergence rate of new adults
  LOGICAL :: loutput_hbr=.false.         ! human bite rate
  LOGICAL :: loutput_vecthostratio=.false. ! ratio of vectors to humans.

! Disease statistics
  LOGICAL :: loutput_pr=.false.          ! parasite ratio
  LOGICAL :: loutput_prd=.false.         ! detectable parasite ratio
  LOGICAL :: loutput_vecinfc=.false.     ! proportion of infective vectors (circumsporozoite protein rate for malaria)
  LOGICAL :: loutput_eir=.false.         ! Entomological Inoculation Rate
  LOGICAL :: loutput_immunity=.false.    ! Proportion of hosts immune
  LOGICAL :: loutput_cases=.false.       ! Proportion of new cases

! Intervention variables
  LOGICAL :: loutput_sit=.false.         ! sit interventions.
  LOGICAL :: loutput_bednet=.false.      ! bednet interventions.

CONTAINS

  SUBROUTINE init_constants

  ! 1: This is a constant rate - Temperature *INdependent* - 12 days 
  rlarv_ermert=0.08333  ! units day**-1 
 
  ! 2: Jepson 1948 cited (not used?) in HM04 - T-dependent rate
  rlarv_jepson=0.011  ! units K**-1 day**-1 

  ! 3: from Bayoh and Lindsay 2003, (see p76 Ermert2010)
  ! the BL2003 paper uses an exponential function with very large factors
  ! we approximate this with a linear function
  rlarv_bayoh=0.005 ! units K**-1 day**-1 

  ! 4: From Craig et al 1999 - this approximates Bayoh very closely [CITATION]
  rlarv_craig=0.00554 !  units K**-1 day**-1  degree day constant for growth rate

  ! TYPE c_vec ::
  !
  ! larvae stage constants
  ! ----------------------§<
  neggmn=60
   
  ! max and min temperature outside of which no larvae survive (c) from Bayoh and Lindsay (2004)
  ! need to combine with ***death rate*** - NOTE COMPATIBLE WITH SCHEME
  rlarv_eggtime=1.0   ! days for egg hatching
  rlarv_pupaetime=1.0 ! days for pupae stage

  ! vector survival constants
  ! maximum temperature Jepson et al., 1947; Depinay et al., 2004 as stated in Bomblies 2008
  ! rtlarsurvmax=40.0 ! maximum temperature (C) above which larvae dies
  
  ! The rflushmin parameter is set to the SURVIVAL average of L1 to L4 larvae
  ! according to Krijn P. Paaijmans1,2*, Moses O. Wandago2, Andrew K. Githeko3, Willem Takken (2007)
  ! 0.89 = L1 larvae flushed out at 17.5% rate after heavy rainfall, L4 at 4.8%... 
  rlarv_flushmin=0.4 ! minimum survivial with high rate 
  rlarv_flushtau=20   ! (mm/day) describes how flushing increases with rainrate 

  ! Larvae growth rate scheme 
  !   1: constant as in Ermert 2010
  !   2: DD - Jepson 1947 as reported by HM04
  !   3: DD - BL2003 (approximated linearly)
  !   4: DD - Craig et al. 1999 

  !
  ! slope and offsets for larvae schemes - Set by nlarv_scheme in mo_control
  !
  rlarv_tmin=12.16 ! 16 old constant - BL=18 slope of parameterization for fractional growth
  rlarv_tmax=38.0  ! 37 BL=34 

  ! larval mass and ecocapacity constants - taken from Bomblies et al. 2009, we assume linear growth
  rmasslarv_stage4=0.45    ! mass in mg of stage 4 adult 
  rbiocapacity=100.0       ! max bio carry capacity of 1m**2 of pool. 

  ! base daily survival  due to preditors and real life (non-lab) factors
  ! before v1.2.9 was fixed to 0.825 
  !   HM04 and Bomblies use 0.88, Ermert 2010 uses 0.825  
  ! After v1.3.0 this base rate is further reduced by Temperature-dependent
  ! Craig et al 1999/Bayoh and Lindsay 2004 
  ! All versions then reduced this further for earlier stage larvae (linear) for flushing effect.
  rlarvsurv=0.987  ! The new parametrization fits with 0.987 to Craig/Bayoh data combined 
                         ! (see code in vectri.f90 for more complete descriptions and tables)

  !
  ! biting parameters
  ! -----------------
  ! daily bite rate of vectors to initiate gonotropic cycle
  ! this fraction manage to locate a host and get a meal each day! 
  ! 
  rbiteratio=0.6      ! Success rate of finding a blood meal per day 
  rzoophilic_tau=30.  ! e-folding rate for zoophilicity (people/ km**2) 
  rzoophilic_min=0.1  ! minimum rate for low population densities 
                               ! (rate lower since adjust to feed on cattle) 


  ! vector mortality functions
  rvecsurv=0.95 ! underlying survival on which temperature based function is imposed.
  rvecsurv_min=0.5

  ! Diffusion coefficient for vector movement from cell to cell
  ! if time step is in units of days, then this has units KM**2/day
  ! thus if a flight path is order of 1km for daily search then this is 1.0 
  ! suggested value is around 0.1-0.3 km**2/day, estimated from Thomas et al plos 1 2013
  rvect_diffusion=0.0

  !END TYPE c_vec
 
  ! TYPE c_wperm
  ! default water fraction of permanent water bodies used if
  ! Sentinel maps are not read in, and also used as minimum if > sentinel
  ! otherwise wperm set to this everywhere
  wperm_default=1.e-6 
  ! END TYPE c_wperm
 
  ! TYPE c_wpond 
  wpond_evap=5       ! evaporation rate in mm/day (*Lv/86400 gives units of Wm^-2) 1.728=50w/m2
  wpond_max=0.2      ! max default water fraction def=0.2 - also used in v130

  ! infiltration rates using the GLDAS soil texture map:
  ! default values from Annex 2 of FAO soil management training methods : 
  ! https://www.fao.org/3/S8684E/S8684E00.htm
  ! units are mm/day (*Lv/86400 gives units of Wm^-2)  e.g. ! 1.728=50W/m2
  ! If no soil map is provided then all cells are set to mean of these three values.
  wpond_infil_clay=50.
  wpond_infil_silt=250.
  wpond_infil_sand=700.

  ! constants specific for npud_vers=1
  wpond_rate=1./1000.      ! increase rate (m^-1)

  ! constants specific for npud_vers=2 (Asare et al. 2016a,b)
  wpond_CN=85         ! 25400/CN-254 curve number 85 (range 80 - 90)
  wpond_min=1.e-6     ! min default water fraction
  wpond_shapep2=1.0   ! shape factor p DIVIDED BY 2 (default p=1, range=0.5-2.0)
  wpond_S=25400/wpond_CN-254 ! 
  wpond_ia=0.1        ! from v1.3.5 initial abstraction (0.05-0.2)
  wpond_depthref=300  ! reference water depth (default=300 mm, range=250-350)
  wpond_ref=0.02      ! reference water fraction (default=10%*rwaterfrac_max, range=0.5% - 2%)

  wurbn_tau=20     ! people per km**2 tau log function
  wurbn_sf=1./200. ! scale factor for urban function

  
  ! offset of water temperature to air temperature
  rwater_tempoffset=2.0 
  
  ! END TYPE c_wpond
 

  ! Distribution of bites in the post v1.3.5 version: rbitehighrisk is a factor between 1.0 and infinity...
  !
  ! rbitehighrisk: the ratio of risk between the higher vulnerable population (in the EI category) and the 
  !                lower vulnerable population (the susceptibles S).  Until we get an agent based approach, 
  !                we used prior bite history as a proxy for vilnerability in this way.
  ! Thus if b is the mean bites per person, k the factor below, bs bites per person in non-vulnerable S group
  ! b= pr k bs + (1-pr) bs, thus bs=b/(1+(k-1)pr)
  !   
  ! Within each categories the bite distribution is still distributed randomly, but the overall distribution of 
  ! bites per person across the population will have a wider distribution.
  !
  ! Setting rbitehighrisk=1.0: no difference in risk, this reproduces the default model prior to v.1.3.5
  ! 
  rbitehighrisk=5.0 ! 1.0 no effect, >1.0 those already infected are assumed to be at high risk - 

  ! number of days after infection for clearance of disease in non-immune subjects
  ! If you are running with immunity switched off then I suggest to leave at high value 90 days
  ! 
  ! A much shorter value is used when immunity is switched on
  ! This is quite short as it is assumed that treatment is sought for most clinical cases
  ! With treatment clearance times are on the order of 2-14 days
  !  e.g. Brandts, Christian H., et al. "Effect of paracetamol on parasite clearance time in 
  !  Plasmodium falciparum malaria." The Lancet 350.9079 (1997): 704-709.)
  ! although it is assumed that it may take several days before treatment is sought.
  rhostclear=15.0

  ! from v1.8 natural clearing is added to the immune category:
  ! The default value is set to 165 days based on 
  ! Klein, E.Y., Smith, D.L., Boni, M.F. and Laxminarayan, R., 2008. 
  ! "Clinically immune hosts as a refuge for drug-sensitive malaria parasites". Malaria Journal, 7(1), p.67.
  ! which is 165/0.8
  ! 
  ! However this can be up to 13 years, see review of: 
  ! Ashley and White, The duration of Plasmodium falciparum infections
  ! Malar J. 2014; 13: 500.
  !. doi: 10.1186/1475-2875-13-500
  rhostimmuneclear=300.0 

  ! malaria transmission probabilities
  !   - these can be from 0.1 to 0.6 - depends on the immunity of the host
  !   - this will be generalized once the garki model is added and will be a function of host category
  ! these values are from LMM of ermert 2010, which in turn are from CITATION  
  ! see also Bonnet, S., et al. "Estimation of malaria transmission from humans to mosquitoes
  ! in two neighbouring villages in south Cameroon: evaluation and comparison of several indices.
  ! " Transactions of the Royal Society of Tropical Medicine and Hygiene 97.1 (2003): 53-59.  (value approx 0.2)
  rpthost2vect_I=0.25   ! I: Infectious (nonimmune)
  rpthost2vect_R=0.1    ! R: Recovered  (immune)
  rptvect2host=0.15

  ! Immunity module - Very simple single compartment immunity treatment to extend model from SEI to SEIR
  !
  ! So model for humans is a SE...EIR model, with n bins for E to get delay for clinical onset
  ! The assumption is that 95% of the population gets full immunity thus EXP(EIRa/TAU)=0.05
  ! The default assumes that an annual EIRa of 100 bites 
  !   is adequate for complete (=95%) immunity following (PAPER HERE)
  ! Thus TAU=-100/ln(0.05)=33.4  - if we use this on daily step the
  !   model is timestep independent as exp(-eir/(n*tau))^n = exp(-eir/tau)
  ! Set to ZERO to switch off immunity.
  rimmune_gain_eira=300 ! default 100 - units EIR   [ -100.0/log(0.05) ]


  ! loss of immunity 
  ! tau set is set so that 95% of people lose immunity after X years.
  ! tau= -X*365/ln(0.05), so 365 gives 3 years loss...
  rimmune_loss_tau=365  ! units days

  !
  ! parasite development constants - Detinova (1962)
  !
  ! Gonotropic cycle
  rtgono=7.7 ! threshold temperature for egg development in vector
                  ! Detinova (1962) gives 4.5 9.9 and 7.7 at RH=30-40,70-80 and 90-100
                  ! this will be implemented in an interpolation scheme
  dgono=37.1
                  ! Detinova (1962) gives 65.4,36.5,37.1 at RH=30-40,70-80 and 90-100
                  ! this will be implemented in an interpolation scheme

  ! Sporogonic cycle from Detinova (1962) - 18.0 used by HM04, 16.0 by Ermert
  rtsporo=16.0 ! threshold temperature for parasite development
  dsporo=111.0


  ! MOVE this to initialization ?
  rhost_infect_init=0.1  ! initial value of host reservoir

  !---------------------
  ! population constants
  !---------------------
  ! Death rate - Units fraction per year (translated later)
  ! This simply causes the death of this frac of the population, who are replaced by malaria naive 
  rpop_death_rate=0.02  

  ! minimum population density (per km**2) allowed in calculation of HBR
  ! if population is below this count then assumed biting on other mammals, otherwise HBR is too high
  ! in very sparse populations 
  rpopdensity_min=1. 

  ! migration level as fraction of population arriving per year with malaria infection
  ! at the moment this is treated as a simple minimum threshold
  rmigration=1.e-5 ! one in a 100,000 people imported cases trickle ONLY when S<this level

  ! latitude limits 
  rlatmax=75. ! turn the model off outside this limit for efficiency (assume malaria free)

  ! quality control parameters
  rqualtemp_min=10.0
  rqualtemp_max=50.0

  ! Interventions
  rbednet_tau=1052 ! days, efolding time for nets

  ! This is from ! Gato et al. 10.3390/insects12050469   = 0.56
  rsit_breed=0.56 
  ! NOTE: How much more likely radiated adults are to die
  ! Bond et al. PLOS 1 2019 https://doi.org/10.1371/journal.pone.0212520 - approx 2  
  rsit_mortality=1.0

  SELECT CASE(ivec)
  !-------------------
  ! ANOPHELES GAMBIAE (S.S. and S.L.)
  !-------------------
  CASE(0)
    wpond_ratio=1.0   ! ratio of temporary ponds selected by vector 
    wperm_ratio=0.01   ! ratio of permanent features, higher for anoph. funestus 
    wurbn_ratio=0.01   ! ratio of urban sites (gutters, tires etc),
    rbeta_indoor=0.2

    rbite_night=0.3
    
    rtsporo=16.0      ! threshold temperature for parasite development
    nsurvival_scheme=2
    nsporo_scheme=1
    vector_name="Anopheles Gambiae"
    idisease=0
    disease_name="Plasmodium Falciparum"

    ! disease output on [ need switch for disease modelling ]
    loutput_prd=.true.
    loutput_eir=.true.
    loutput_cases=.true.
    loutput_vecinfc=.true.
    loutput_immunity=.true.
    loutput_hbr=.true.
    loutput_emergence=.true.
    
    ! negg - size of batch*female ratio
    !
    ! wide range
    ! ~180 Yaro et al . https://doi.org/10.1093/jmedent/43.5.833
    ! ~170 wet season, ~100 dry season Yaro etal 2012 https://doi.org/10.1016/j.jinsphys.2012.04.002
    ! ~50 Christiansen-Jucht Parasites & Vectors volume 8, Article number: 456 (2015)
    ! 90-100 Hogg and Hurd 97 doi:10.1017/S0031182096008542
    ! 
    neggmn=60
    
  !-------------------
  ! ANOPHELES FUNESTUS
  !-------------------
  CASE(1) 
    wpond_ratio=0.5   ! usage ratio of temporary ponds selected by vector 
    wperm_ratio=0.7   ! usage ratio of permanent features, higher for anoph. funestus 
    wurbn_ratio=0.1   ! ratio of urban sites (gutters, tires etc),
    rbite_night=0.3
    rbeta_indoor=0.2
    rtsporo=16.0      ! threshold temperature for parasite development
    nsurvival_scheme=2
    nsporo_scheme=1
    vector_name="Anopheles Funestus"
    idisease=0
    disease_name="Plasmodium Falciparum"

    ! disease output on [ need switch for disease modelling ]
    loutput_prd=.true.
    loutput_eir=.true.
    loutput_cases=.true.
    loutput_vecinfc=.true.
    loutput_immunity=.true.
    loutput_hbr=.true.
    loutput_emergence=.true.

    ! Mouatcho et al 
    neggmn=60
  
  !-------------------
    ! ANOPHELES SACHAROVI
    ! Calibration taken from
    ! Karypidou, Maria Chara, et al.
    ! "Projected shifts in the distribution of malaria vectors due to climate change."
    ! Climatic Change 163.4 (2020): 2117-2133.
    ! Other refs used for this were:
    ! 
    ! 1) Kampen, H., Proft, J., Etti, S. et al. Individual cases of autochthonous malaria in Evros Province, northern Greece: entomological aspects. Parasitol Res 89, 252–258 (2003). https://doi.org/10.1007/s00436-002-0746-9
    !
    ! 2) Malaria Atlas Project (https://malariaatlas.org/bionomics/anopheles-sacharovi/)
    !
    ! 3) Tavşanoğlu, N., Ağlar, S., 2008. The vectorial capacity of Anopheles sacharovi in the malaria endemic area of Şanlıurfa, Turkey. Eur. Mosq. Bull. 26, 18–23 (https://e-m-b.myspecies.info/content/vectorial-capacity-ianopheles-sacharovii-malaria-endemic-area-%C5%9Fanl%C4%B1urfa-turkey)
    !
    ! 4) Kiszewski, A., Mellinger, A., Spielman, A., Malaney, P., Sachs, S.E., Sachs, J., 2004. A global index representing the stability of malaria transmission. Am. J. Trop. Med. Hyg. 70, 486–498.
  !-------------------
  CASE(2)
    wpond_ratio=1.0   ! ratio of temporary ponds selected by vector 
    wperm_ratio=0.02   ! ratio of permanent features, higher for anoph. funestus 
    wurbn_ratio=0.01   ! ratio of urban sites (gutters, tires etc),
    rbite_night=0.3
    rbeta_indoor=0.2
    rtsporo=16.0      ! threshold temperature for parasite development
    nsurvival_scheme=2
    nsporo_scheme=1

    ! manual calibration 
    rtgono=9.9
    dgono=36.7
    rlarv_tmin=15.5
    rlarv_tmax=35
    rlarvsurv=0.85

    vector_name="Anopheles Sacharovi"
    idisease=0
    disease_name="Plasmodium Falciparum"

    ! disease output on [ need switch for disease modelling ]
    loutput_prd=.true.
    loutput_eir=.true.
    loutput_cases=.true.
    loutput_vecinfc=.true.
    loutput_immunity=.true.
    loutput_hbr=.true.
    loutput_emergence=.true.
    neggmn=60
    
  !-------------------
  ! AEDES ALBOPICTUS
  !-------------------
  CASE(10)

  ! Calibration from GA, Garrido Zornoza et al. (2024) [ref]: https://doi.org/10.1098/rsif.2024.0319)
  ! and references therein (table Suplementary Information) for parameter values.
  ! Nomenclature: GA = Genetic Algorithm calibration against Italian ovitrap data
  !                X = Not included in calibration
  ! Note: If no reference don't trust the value/ value is to be updated

    vector_name  = "Aedes albopictus"
    disease_name = "Dengue [non-functional]"
    idisease     = -1    ! off: will be 10 eventually

    ! Hydrology ==============================
    wpond_ratio=0.00944  !(GA) ratio of temporary ponds selected by vector 
    wperm_ratio=0.1      !(X)  ratio of permanent features, higher for anoph. funestus 
    wurbn_ratio=0.02149  !(GA) ! ratio of urban sites (gutters, tires etc),
    rlarv_flushmin=78.50 !(GA) Flushing factor by precipitation

    ! Vector life-cycle ======================
    ! Batch~80 Armbruster and  Hutchinson https://doi.org/10.1603/0022-2585-39.4.699
    ! Batch~40-90 Table 6 Delatte et al,2009 https://doi.org/10.1603/033.046.0105
    ! Batch 86.9 to 102.5 - bond et al. https://doi.org/10.1371/journal.pone.0212520
    ! Batch 70-100 Muhammed PLoS One. 2020; 15(11): e0241688. Aedes albopictus (Skuse)

    neggmn=82.9793         !(GA) Average number of laid eggs per batch 
    nsurvival_scheme=4     ! Adult, egg and larvae temperature-dependent
                           ! survival scheme (Metelmann, 2019) 
                           ! [ref]: https://doi.org/10.1098/rsif.2018.0761
    rlarv_tmin=9.938       !(GA) Threshold water temperature for larval development [°C]
    rtgono=7.120           !(GA) Threshold air temperature for gonotrophic cycle [°C]
    dgono=100.545          !(GA) Degree-days necessary for egg development
    rbiocapacity=218.091   !(GA) Maximum larvae biomass per unit surface area [mg x m^{-2}]
    !aovi=0.1143           !(GA) Scale-factor "Effective ovitrap area" (Supplementary Information B)

    rlarvsurv = 1. 
    
    ! disease output off [ need switch for disease modelling ]

    loutput_prd=.false.
    loutput_eir=.false.
    loutput_cases=.false.
    loutput_vecinfc=.false.
    loutput_immunity=.false.
    loutput_hbr=.false.
    loutput_emergence=.false.

    ! Disease/parasite (non-functional) ==============
    rbeta_indoor =  0.2  ! (X)
    rbite_night  =  0.3  ! (X)

    nsporo_scheme=  2    ! Exponental EIP(T) [ref]: (missing)

    ! Use nsporo_scheme = 1 for Detinova
    rtsporo      = 18.0  ! threshold temperature for parasite development [ref]: (missing)
    dsporo       =111    ! accumulated degrees for complete development  [ref]: (missing)

  !-------------------
  ! AEDES AEGYPTI
  !-------------------
  CASE(11)
    
    vector_name  = "Aedes aegypti"
    disease_name = "Dengue [non-functional]"
    idisease     = -1 ! off: will be 11 eventually
    
    ! Hydrology ==============================
    wpond_ratio=0.00944   ! ratio of temporary ponds selected by vector - value taken from albopictus calibration
    wperm_ratio=0.1       ! ratio of permanent features, higher for anoph. funestus
    wurbn_ratio=0.02149   ! ratio of urban sites (gutters, tires etc) - value taken from albopictus calibration

    ! Vector life-cycle ======================
    nsurvival_scheme=5 ! [ref]: (missing)
    neggmn=50          ! Batch 97.0–102.3 - [ref]: Bond et al. https://doi.org/10.1371/journal.pone.0212520

    rlarv_tmin=10.     ! Threshold water temperature for larval development [°C]
                       ! [ref]: (missing)
    rtgono=14.5        ! Threshold air temperature for gonotrophic cycle [°C]
                       ! [ref]: Caldwell et al. https://doi.org/10.1038/s41467-021-21496-7
    dgono=100.             ! Degree-days necessary for egg development [ref]: (missing - value from albopictus)
    rbiocapacity=218.      ! Maximum larvae biomass per unit surface area [mg x m^{-2}] ref]: (missing - value from albopictus)

    rlarvsurv = 1.
    ! disease output off [ need switch for disease modelling ]

    loutput_prd=.false.
    loutput_eir=.false.
    loutput_cases=.false.
    loutput_vecinfc=.true.
    loutput_immunity=.false.
    loutput_hbr=.false.
    loutput_emergence=.false.

    ! Disease/parasite (non-functional) ==============
    rbeta_indoor=0.2
    rbite_night=0.3

    nsporo_scheme= 3     ! Exponental EIP(T) [ref]: (missing)

    ! Use nsporo_scheme = 1 for Detinova
    rtsporo = 18.0   ! threshold temperature for parasite development [ref]: (missing)
    dsporo  =111     ! accumulated degrees for complete development  [ref]: (missing)

    
  CASE DEFAULT
    PRINT *, "case selection incorrect, needs to be from 0,1,2,10,11"
    STOP
  END SELECT
  PRINT *, '%I: Vector: ',vector_name
  PRINT *, '%I: Disease: ',disease_name
  

  ! place the larval progression rates into an array
  rlarvmature(1,:)=(/0.0,rlarv_ermert/)  ! temperature independent
  rlarvmature(2,:)=(/rlarv_jepson,-rlarv_tmin*rlarv_jepson/)
  rlarvmature(3,:)=(/rlarv_bayoh,-rlarv_tmin*rlarv_bayoh/)
  rlarvmature(4,:)=(/rlarv_craig,-rlarv_tmin*rlarv_craig/)

  END SUBROUTINE init_constants
  
END MODULE mo_constants
