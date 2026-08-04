MODULE mo_const
  implicit none
! This module deals with array declarations, model parameters and the 
! selection of constants by disease case.
!
! Author: Miguel Garrido Zornoza 2024 
! Contact: mgarrizoraca@gmail.com
!
! Index
!
! === 1. DECLARATIONS ===
! === 2. EXECUTABLE STATEMENTS ===
! === 3. SUBPROGRAM SECTION ===

! === 1. DECLARATIONS ===
! Model Parameters ----------------------------------
    
    !********** Integration **********************
    integer :: nsteps       ! Number of integration steps (days) (either Namelist of Read from file)
    integer :: nagent       ! Number of agents
    integer :: nagent_max   ! Max agent-slot capacity for population growth; defaults to nagent
    real, allocatable    :: scale(:)   ! Scale factor to transform numbers into a densities
    real, allocatable    :: scaleI(:)  ! Inverse of scale
    !integer :: nalive       ! Number of alive agents
    real    :: dt = 1.      ! Time step (fixed)
    real    :: da = 1./365. ! Age increase per time step 
    integer :: ncid_out     ! ID of output NetCDF file
    integer :: ncid_in      ! ID of input NetCDF files
    integer :: ncid_grp(4)  ! ID of groups: 1 - Vector ; 2 - Human ; 3 - Climate ; 4 - Hydro
    integer :: ncid_sbgrp(7)! ID of disease subgroups: 1 - Susceptible ; 2 - Exposed ; 3 - Infected ; 4 - Asymptomatic ; 5 - Recovered
                            !                          6 - Immunity ; 7 - New Cases (Inew)        
    integer :: TempVarID, ncTempID
    integer :: RainVarID, ncRainID
    integer :: AreaVarID, ncAreaID
    integer :: ImmVarID, ncImmID   ! IDs for immunity forcing file


    real    :: eps = 1e-15  ! Numerical tolerance 
    real    :: FillValue    ! Population density FillValue
    real    :: FillValue_rain ! Rainfall Fill Value
    real    :: FillValue_temp ! Temperature Fill Value
    real, parameter :: pi = 4*atan(1.) ! Pi 
    real, parameter :: Re = 6371.009   ! Mean radius of the Earth [km]

    !********** Mobility and people **************************

    real, allocatable :: Q(:,:)           ! Probability of visit matrix for short trips (based on the mobility scheme)
    real, allocatable :: Q_2(:,:)         ! Probability of visit matrix for long trips  (based on the mobility scheme)
    real, allocatable :: Q_short(:,:)     ! Mobility "dice" for daily trips, used when agents=.true.
    real, allocatable :: Q_long(:,:)      ! Mobility "dice" for long overnight trips
    real, allocatable :: dist(:,:)        ! Distance matrix

    logical, allocatable :: mask_pop(:)    ! (nxy)
    logical, allocatable :: mask_grav(:,:) ! (nxy,nxy) 2D long array with r_cut off information 
    logical, allocatable :: mask_mob(:)    ! (nxy) Mask with the grid points where agents can move - combines mask_pop and mask_grav

    integer, allocatable :: npeop(:)    ! Number of agents in each grid cell
    ! Chunk size for SCHEDULE(STATIC, agent_chunk) in mo_timestep.f90 -- keep
    ! in sync with the pragma there.
    integer, parameter :: agent_chunk = 500
    ! npeop(:), broken down by each agent's owning thread (nxy,nthreads) --
    ! fixed per agent for its life under STATIC scheduling, so written
    ! lock-free, one column per thread.
    integer, allocatable :: npeop_thread(:,:)
    ! Fixed total (dead+alive) slots per (cell,thread), snapshotted once at
    ! init. nslots_thread-npeop_thread = a thread's current dead-slot capacity.
    integer, allocatable :: nslots_thread(:,:)
    ! sum(nslots_thread,dim=2), cached once at init -- each cell's initial
    ! (all-active) agent count, used as the denominator for today's
    ! active-agent fraction in agents_pre_diagnostics.
    integer, allocatable :: npeop_init(:)
    real, allocatable :: HA(:)          ! Human to agent ratio
    ! Today's claimable birth tickets per (cell,thread), set in
    ! agents_pre_diagnostics; claimed lock-free by each thread from its own
    ! column.
    integer, allocatable :: nbirths_left(:,:)
    real, allocatable :: pop_dens(:)    ! 1D long array for human population density 
    real, allocatable :: Ipop_dens(:)   ! Inverse of 1D long array for human population density 
    real, allocatable :: D(:)           ! Dilution factor
    real              :: P_a            ! Number of agents per person in the simulation
    real, allocatable :: A_cell(:)      ! Area of grid cells

    real, allocatable :: age_weights(:)   ! Array with age structure
    integer, allocatable :: age_counts(:) ! 1D array of age structure (for output)
    integer :: age_blocks(16) = (/ 1,2,3,4,5,6,7,8,10,12,15,20,30,45,60,80 /)  ! Age intervals to disaggreate diagnostics
    ! Labels of disaggregated age structure (to improve --> automatise based on age_blocks(:))
    !character(len=100) ::  I_age_names(8)= [character(len=20) :: "I_0<","I_1-4","I_5-9","I_10-14","I_15-19","I_20-39","I_40-59","I_60>"]
    !character(len=100) ::  A_age_names(8)= [character(len=20) :: "A_0<","A_1-4","A_5-9","A_10-14","A_15-19","A_20-39","A_40-59","A_60>"]
    !character(len=100) ::  imm_age_names(8)= [character(len=20) :: "imm_0<","imm_1-4","imm_5-9","imm_10-14","imm_15-19","imm_20-39","imm_40-59","imm_60>"]
    integer, parameter :: STR_LEN = 100
    ! Declare as allocatable
    character(len=STR_LEN), allocatable :: I_age_names(:), A_age_names(:), imm_age_names(:), I_new_age_names(:)
    !character(len=10), dimension(3)      :: prefixes = ["I_  ", "A_  ", "imm_"]
  
    !********* Spin Up ***************************

    real, allocatable :: SU_new(:) ! (nxy) Array with year average to test convergence
    real, allocatable :: SU_old(:) ! (nxy) Array with year average to test convergence
    logical :: SU_conv ! Convergence flag
    real :: SU_tol     ! Tolerance for convergence
  !  real :: SU_old     ! 

    !********** Grid *****************************
    integer :: nlon  ! Number of longitude points
    integer :: nlat  ! Number of latitude points
    integer :: nxy   ! Number of lattice points (=nlat*nlon)
    integer :: ntime ! Number of time steps in forcing input data

    real    :: dx  ! Horizontal discretization
    real    :: dy  ! Vertical discretization

    integer :: seed=1234      ! 
    integer :: spin_up=1      ! Spin-up 

    ! Conceptual case
    integer, parameter :: ncity=1  ! Number of radial cities in the grid
    real, parameter ::      L=100. ! Latice side length (km)
    !--

    real, allocatable :: lon_coord(:)  !
    real, allocatable :: lat_coord(:)  !
    real, allocatable :: time_coord(:)  !

    integer :: xy_seed                  !
    ! Mapped 2D grid arrays
    integer, allocatable :: x_coord_1d(:)  ! 
    integer, allocatable :: y_coord_1d(:)  !

    real, allocatable :: grid(:,:)         ! (nlon,nlat)
    real, allocatable :: grid_clim(:,:,:)    ! (nlon,nlat,ntime)

    !********** Disease **************************

    real, allocatable, target :: S(:) ! 1D long array for Sensitive density
    real, allocatable, target :: Sa(:,:)! (nxy,nage_blocks)
    real, allocatable, target :: E(:) ! 1D long array for Exposed density
    real, allocatable, target :: Ea(:,:)! (nxy,nage_blocks)
    real, allocatable, target :: I(:) ! 1D long array for Infected density
    real, allocatable, target :: Ia(:,:)! (nxy,nage_blocks) 
    real, allocatable, target :: I_new(:) ! 1D long array for New cases (Infected)
    real, allocatable, target :: Ia_new(:,:)! (nxy,nage_blocks) 
    real, allocatable, target :: A(:) ! 1D long array for Asymptomatic density
    real, allocatable, target :: Aa(:,:)! (nxy,nage_blocks)
    real, allocatable, target :: R(:) ! 1D long array for Recovered density
    real, allocatable, target :: Ra(:,:)! (nxy,nage_blocks)

    ! Per-thread, per-block staging (nxy,nthreads,nage_blocks) for the age-
    ! disaggregated arrays above -- one column set per BLOCK, not per exact
    ! age, mirroring how Iage_stat_ptr(:,:)%arr_p already aliases many ages
    ! onto the same block array (see find_block in mo_grid.f90).
    ! Sa/Ea/Ra have no output flag and no reader anywhere (mo_netcdf.f90) --
    ! not staged here; agents_diagnostics skips writing them (see istat check).
    real, allocatable, target :: Ia_priv(:,:,:), Aa_priv(:,:,:), Ia_new_priv(:,:,:)
    real, allocatable, target :: imm_a_priv(:,:,:), N_a_priv(:,:,:)

    type array_pointers
      real, pointer :: arr_p(:)
      ! Per-thread staging (nxy, nthreads): each thread accumulates into its own
      ! column lock-free; agents_post_diagnostics sums columns into arr_p once a day.
      ! Pointer (not allocatable): age-disaggregated entries that share an age
      ! block (see find_block) must also share the same staging column, or the
      ! reset/merge cost scales with the number of exact ages (80) instead of
      ! blocks (16) -- see Sa_priv etc. below.
      real, pointer :: arr_p_priv(:,:)
    end type array_pointers
    
    type(array_pointers) :: status_pointer(6)  ! SEIAR+I_new
    type(array_pointers), allocatable :: Iage_stat_ptr(:,:)  !(istatus,iage)

    !--- Cholera ---
    real, allocatable :: B(:) ! 1D long array for Bacterial density
    real, allocatable :: F(:) ! 1D long array for Force of infection

    real, allocatable :: exc(:) ! 1D long array for the excretion events
    real, allocatable :: exc_clim(:) ! 1D long array for clim-driven excretion events

    real, allocatable :: B_old(:) !  
    real, allocatable :: A_old(:) ! 

    ! Cholera parameters 
    
    real :: mu_B, theta_e, theta_p, mu, rho, sigma, gamma, alpha, beta ! Disease
    real :: birth_rate ! Daily per-agent birth probability; defaults to mu (see namelist_const)
    ! Per-agent daily death probability by integer age (0-79); materialized
    ! from mortality_file if given, else broadcast from the scalar mu (see
    ! namelist_const). Agent-based death checks only -- the non-agent bulk
    ! SIAR path keeps using the scalar mu.
    real :: mu_age(0:79)
    ! b(t): yearly birth-rate series, linearly interpolated daily (see
    ! interp1). birth_years(:) is years elapsed since simulation start
    ! (0,1,2,...), not calendar years -- rebased on read. Materialized from
    ! birthrate_file if given, else a length-1 series equal to birth_rate.
    real, allocatable :: birth_years(:), birth_vals(:)
    real :: D_pop, H_0, D_grav, m       ! Pop. density and mobility
    real :: B_0, fS_0, fI_0, fA_0, fR_0 ! Initial conditions

    !--- Malaria ---

    real, allocatable :: EIR(:)   ! 1D long array for Entomological Inoculation Rate
    real, allocatable :: hbr(:)   ! 1D long array for Human Biting Rate
    real, allocatable :: imm(:)   ! 1D long array for Endemicity level / Immunity
    ! Per-thread staging (nxy, nthreads) for EIR/hbr/imm -- same pattern as arr_p_priv above
    real, allocatable :: EIR_priv(:,:), hbr_priv(:,:), imm_priv(:,:)
    real, allocatable :: imm_2D(:,:) ! (nx,ny) 2D array for immunity forcing at slice itime
    real, allocatable, target :: imm_a(:,:) !(nxy,nage_blocks) Immunity disaggregated by age
    real, allocatable, target :: N_a(:,:) !(nxy,nage_blocks)   Agent number disaggregated by age
    ! Host-vector parameters

    real :: K_h                         ! 
    real :: k_NB                        ! Negative Binomial dispersion coefficient
    !real :: srho

    integer :: iip 
    real :: bite_night, bite_day        ! 
    real :: m_short, m_long             ! Fraction of short and long trip travellers
    real :: r_ret                       ! Time scale for long trip return home
    real :: fE_0                        ! Initial conditions

    real :: b_rate                      ! Mosquito biting rate (bites/mosquito/day)

    real :: e_0, e1, e2, A1, e_th, mat_rate ! Immunity - immunity acquisition parametrization
    real :: d_sig,d_mu,sig_1,mu_1           ! Immunity - clearance times parametrization
    real :: fA_chr                          ! Fraction of chronic asymptomatics
    integer :: tau_chr                      ! Duration of chronic parasitaemia
 
    real :: alph_max, alph_min, k_alph      ! Symptomatics
    !real :: sig_m, e_m                     ! Old scheme

    ! Sigmoidal curve param ~ slope
    real :: m_a, m_c, k_m !

    ! Sigmoidal curve param ~ inflection point
    real :: i_star_a, i_star_c, k_star


    real :: d_c, d_a, k_e              ! 

    !--- VECTRI/Malaria ---
    ! mo_vectri.f90
    integer, parameter :: ninfv=25       ! Resolution of vector parasite development
    real :: P_v0                         ! Probability of vector to human infection upon biting from fully infective vector
    real :: P_h0                         ! Probability of human to vector infection upon biting from a susceptible vector to an infected human host
    real :: P_max  

    real, allocatable :: rvect(:,:)         ! (0:ninfv,nlon*nlat)
    integer, allocatable :: nbites(:)       ! (nlon*nlat) Infective bites
                                            ! (vectors that were infected upon
                                            ! bitting a human)
    real, allocatable :: rgonof(:)          ! Gonotrophic cycle 
    real, allocatable :: m_0(:), m_1(:), m_all(:)  ! Vector to host ratio times the vector biting rate

    ! VECTRI -- soil
    real :: soilinfil_SA=(1./3.)*(50+250+750)

    !********** Clima **************************
    ! Pointers (not allocatable) so that spin-up can redirect them to a
    ! climatology and swap back to the real record afterwards -- see
    ! mo_spinup.f90. ALLOCATE works on POINTER arrays exactly as before.
    real, pointer :: rainfall(:,:) => null()    ! 2D long array for rainfall (nxy,t)
    real, pointer :: t2m(:,:) => null()         ! 2D long array for temperature (nxy,t)

    real :: point_rain, point_temp

    !********** NetCDF **************************
    real                 :: fill_pop       !
    ! NetCDF IDs
    integer, allocatable :: arr_VarID(:)
    integer :: DimId(4) = [1,2,3,4] !(lon,lat,time,age)
    integer :: Var3D
    ! Attribute list
    character(len=100), allocatable ::  att_list(:)     ! List of NetCDF file attributes (system params)


    ! === 2. SUBPROGRAM SECTION ===
    CONTAINS

    subroutine init_age_labels()
        ! Local use indexes to initialize age names
        integer :: i_age, p_age, n_age
        character(len=10), dimension(4) :: prefixes = ["I_   ", "A_   ", "imm_ ", "Inew_"]

        n_age = size(age_blocks)
        allocate(I_age_names(n_age), A_age_names(n_age), imm_age_names(n_age), I_new_age_names(n_age))

        do i_age = 1, n_age
            do p_age = 1, 4
                select case(p_age)
                    case(1); call build_label(I_age_names(i_age),     prefixes(p_age), i_age, n_age, age_blocks)
                    case(2); call build_label(A_age_names(i_age),     prefixes(p_age), i_age, n_age, age_blocks)
                    case(3); call build_label(imm_age_names(i_age),   prefixes(p_age), i_age, n_age, age_blocks)
                    case(4); call build_label(I_new_age_names(i_age), prefixes(p_age), i_age, n_age, age_blocks)
                end select
            end do
        end do
    end subroutine init_age_labels

    subroutine build_label(str, pre, idx, total, blocks)
        character(len=*), intent(out) :: str
        character(len=*), intent(in)  :: pre
        integer, intent(in)           :: idx, total, blocks(:)
        
        if (idx == 1) then
            write(str, '(A, "0-", I0)') trim(pre), blocks(idx)-1
        else if (idx < total) then
            write(str, '(A, I0, "-", I0)') trim(pre), blocks(idx-1), blocks(idx)-1
        else
            write(str, '(A, I0, "+")') trim(pre), blocks(idx-1)
        end if
        str = adjustl(str)
    end subroutine build_label

    subroutine const_disease(idis)
      implicit none

      !==================================
      !
      ! Case 0: Cholera
      ! Case 1: Malaria [Non-functional]
      ! Case 2: Dengue  [Non-functional] 
      !
      !==================================

      integer, intent(in) :: idis
      character(len=100) :: disease_name
      birth_rate = -1. ! Sentinel: namelist_const sets birth_rate = mu if still negative
      ! Disease-specific values
      SELECT case(idis)
      case (0)
        disease_name="Cholera"
        !
        ! Disease ---------------------------------------------------------------------
        ! - Default disease values from [ref:c1], [ref:c2]
        !   and references therein (see Supp. Information in Rinaldo, table S2)
        !
        mu_B =0.2         ! Bacterial decay rate                   [day^-1]
        theta_e=0.141     ! (normalized) Baseline excretion/contamination rate from infected population [day^-1]
        theta_p=0.141     ! Effect of precipitation in the climate-driven excretion rate                [mm^-1]
        mu   =1./(61.*365)! Background human mortality rate        [day^-1]
        rho  =1./(3.*365) ! Loss of immunity rate                  [day^-1]
        sigma=0.2         ! Proportion of symptomatics             [fraction]
        gamma=0.2         ! Recovery rate                          [day^-1]
        alpha=0.004       ! Death rate (infection or other causes) [day^-1]
        !    
        ! Mobility ---------------------------------------------------
        m_short=0.0   ! Fraction of mobile population (could be an array to account for age, ... but is set to one constant for now)
        D_grav=2.     ! e-folding distance for gravity model [km] ; Rinaldo et al. (2012) gives 100km for Haiti's epidemic --> not very realistic
        beta=1.       ! Contact rate [day^-1]
        
        ! Idealized world parameters
        D_pop=10   ! e-folding decay for radial city         [km]
        H_0=2000   ! Human population density at city centre [km^2]
        
        ! Default initial conditions ---------------------------------
        B_0 =0.1  ! Initial bacterial concentration [dimensionless] (has been normalized by K --> See referenced model)
        fS_0=1.   ! Susceptible  [fraction]
        fI_0=0.   ! Infected     [fraction]
        fA_0=0.   ! Asymptomatic [fraction]
        fR_0=0.   ! Recovered    [fraction]

        ! Attribute list 
        !att_list = ['mu_B','theta_e', 'theta_p', 'mu', 'rho', 'sigma', 'gamma', 'alpha', 'm', 'D_grav', 'beta']

      case(1)
        disease_name="Malaria"
        !
        ! Default disease values for human host
        iip = 10              ! Intrinsic incubation period [day] Cowman et al 2016 [DOI: https://doi.org/10.1016/j.cell.2016.07.055]
        bite_night = 0.       ! Base daily probability to get bitten overnight. Should be a function of wellfare index (availability of bednets, ...)
        bite_day   = 0.       ! Base daily probability to get bitten during day (relevant for short daily trips and vectors that are active during day hours)
        P_v0 = 0.3            ! Base vector to human transmission probability  Ermert et al. 2011 [DOI:]
        P_h0 = 0.2            ! Base human to vector transmission probability          "  "
        P_max= 0.2            ! Maximum transmission probability ~ 0.2 +- 0.15 Churcher et al. 2013 [DOI:]
                              !                                  ~ 0.125       Bousema  et al. 2011 [DOI:] ---> and references therein | Ouedraogo 2009 [DOI:]
                              !                                                                                                        | Schneider 2007 [DOI:]
                              ! Vector biting rate [day^(-1)]
        b_rate = 0.5          ! 20 [bites/person/day] - mean of 1.6 bites/person/hour from 18:00 - 6:30 (~ 1.6*12.5=20) Nzioki et al. 2023 [DOI:]
        K_h = 0.0003          ! Free (tuning) parameter
        k_NB = 2.5            ! Guelbéogo et al. 2018 [DOI: https://doi.org/10.7554/eLife.32625]
      !  srho = 1.0

        ! mu  = 1./(61.*365)    ! Background human mortality rate [day^-1] [ref] 
        mu  = 0.0416/365.   ! Birth and mortality rate - Exponential fit to Senegal's 2000 WorldPop age structure
      !  mu  = 0.0354/365.  ! Birth and mortality rate - Exponential fit to Senegal's 2020 WorldPop age structure 
        !-- Immunity scheme --!
        e_0    = 0.2
        !e_0    = 0.09     ! Base increase in endemicity level [per infectious bite]                  [x]
        e1     = 0.5*e_0  ! e-folding factor in boosted maternal/naive immunity acquisition (fast) [e_0]
        e2     = 10*e_0   ! e-folding factor in gradual immunity acquisition (slow)                [e_0]
        A1     = 0.9      ! Coefficient weighting each time scale
        e_th   = 0.001    ! Threshold endemicity level value for R --> S transition                  [x]
 
        mat_rate = log(2.)/(6.*30)  ! Loss rate of maternal immunity = ln(2)/(Half-life of maternal immunity) [day^-1] (~ 6 months)
                                  !
                                  ! 3-9 months Gupta 1999 [DOI:]
                                  ! 3   months Ghani 2009 [DOI:]
        !-------------------------!
        ! Immunity waning scheme  !
        !
        ! t_e(1/2): Half-life of clinical immunity
        ! ln(2)/(t_e(1/2))  = 5   [yr] Filipe 2007 [DOI:]
        !                   = 6.9 [yr] Ghani  2009  [DOI:]
        !
        ! Scheme: t_e(1/2) = t_c(1/2) + (t_a(1/2) - t_c(1/2))*(1-e(-a/k_e))
        d_c = 200.                ! t_c(1/2)
        d_a = 10.*365             ! t_a(1/2)
        k_e = 15.                 ! k_e: e-folding age for maturation of immunity half-life
        !-------------------------!
        ! Clearance time scheme   !
                                  ! The reported mean and std are those of the corresponding normal distribution.
        d_mu    = -3.54           ! mu_1 = 5.2  (MT (PfPR ~ 0 %) [Sama et al. 2006a]), mu_2 = 1.66 (Ghana (PfPR ~ 75%) [Bretscher et al. 2011])
        d_sig   =  0.47           ! sig1 = 0.73 (MT (PfPR ~ 0 %) [Sama et al. 2006a]), sig2 = 1.20 (Ghana (PfPR ~ 75%) [Bretscher et al. 2011])
        sig_1   =  0.73           ! 
        mu_1    =  5.2            !
        !---------------------------------!
        ! Symptomatic probability scheme  !
                          ! These values are only relevant when 
        fA_chr   = 0.05   ! Fraction of chronic asymptomatics [unkown]
        tau_chr  = 365.*2    ! Duration of chronic parasitaemia  [unkown]
                          !
        k_alph   = 1.
        alph_min = 0.28   !    We take the lowest we can find from literature focusing on highly endemic areas reporting (with PCR) adult prevalence
                          !    1-0.311 (Malawi) Topazian    2020 [DOI:]
                          !    1-0.482 (DCR)    Mvumbi      2015 [DOI:]
                          !    1-0.520 (Gabon)  Dal-Bianco  2007 [DOI:]
                          !    1-0.680 (Ghana)  Heinemann   2020 [DOI:]
        ! So far this one ---> 1-0.721 (Ghana)  Owusu-Agyei 2002 [DOI:] 
        alph_max = 1.    !

        ! sig_m  = 20.   ! Old scheme
        ! e_m    = 0.35  ! Old scheme  

        ! Sigmoidal curve param ~ slope
        m_a = 10
        m_c = 60
        k_m = 10

        ! Sigmoidal curve param ~ inflection point
        i_star_a = 0.15  
        i_star_c = 0.5
        k_star   = 10

        ! Mobility [non-functional ; wait for funding (Marie-Curie!)]---------------------------------------------------

        m_short=0.    ! Fraction of mobile population making short daily trips (could be an array to account for age, ... but is set to one constant for now)
        m_long =0.    ! Fraction of mobile population starting long overnight trips
        r_ret  =1./5. ! Rate of long trip return [dayy^-1]
        D_grav =2.    ! e-folding distance for gravity model [km] 

        ! Idealized world parameters
        D_pop=10   ! e-folding decay for radial city         [km]
        H_0=2000   ! Human population density at city centre [km^2]

        ! Default initial conditions ---------------------------------
        
        fS_0=1.   ! Susceptible  [fraction]
        fE_0=0.   ! Exposed      [fraction]
        fI_0=0.   ! Symptomatic  [fraction]
        fA_0=0.   ! Asymptomatic [fraction]
        fR_0=0.   ! Recovered    [fraction]

        ! Attribute list 
        !att_list = ['m_short','m_long', 'bite_night']

      case(2)
        disease_name="Dengue"

      case default
        print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
        STOP
      end SELECT

      print *, "Disease: ", disease_name
    end subroutine const_disease


    subroutine read_mortality_file(path, mu_age)
    !===
        ! Reads a two-column (age,mortality_rate) CSV with a header row into
        ! mu_age(0:79), indexed by the file's own age column (not line order).
        implicit none
        character(len=*), intent(in) :: path
        real, intent(inout) :: mu_age(0:79)

        ! Local use only
        character(len=200) :: header
        integer :: age_val, io_status, n_read
        real :: rate_val

        OPEN(UNIT=21, FILE=trim(path), STATUS='OLD', ACTION='READ')
        READ(UNIT=21, FMT='(A)') header ! Skip header row

        n_read = 0
        do
            READ(UNIT=21, FMT=*, IOSTAT=io_status) age_val, rate_val
            if (io_status /= 0) EXIT
            if (age_val >= 0 .and. age_val <= 79) then
                mu_age(age_val) = rate_val
                n_read = n_read + 1
            end if
        end do
        CLOSE(UNIT=21)

        if (n_read /= 80) then
            print *, "Warning: mortality_file did not have exactly 80 age rows (0-79); found", n_read
        end if
    end subroutine read_mortality_file


    subroutine read_birthrate_file(path, birth_years, birth_vals)
    !===
        ! Reads a two-column (year,birth_rate) CSV with a header row.
        ! birth_years(:) is rebased to years-since-first-row (0,1,2,...) --
        ! the model never needs to know the real calendar year.
        implicit none
        character(len=*), intent(in) :: path
        real, allocatable, intent(out) :: birth_years(:), birth_vals(:)

        ! Local use only
        character(len=200) :: header
        real :: dummy_years(200), dummy_vals(200)
        integer :: year_val, num_elements, io_status
        real :: rate_val

        OPEN(UNIT=22, FILE=trim(path), STATUS='OLD', ACTION='READ')
        READ(UNIT=22, FMT='(A)') header ! Skip header row

        num_elements = 0
        do
            READ(UNIT=22, FMT=*, IOSTAT=io_status) year_val, rate_val
            if (io_status /= 0) EXIT
            num_elements = num_elements + 1
            dummy_years(num_elements) = real(year_val)
            dummy_vals(num_elements) = rate_val
            if (num_elements >= size(dummy_years)) then
                print *, "Warning: The birth-rate array is full. Some data may not have been read."
                EXIT
            end if
        end do
        CLOSE(UNIT=22)

        allocate(birth_years(num_elements))
        allocate(birth_vals(num_elements))
        birth_years(:) = dummy_years(1:num_elements) - dummy_years(1)
        birth_vals(:) = dummy_vals(1:num_elements)
    end subroutine read_birthrate_file


    function interp1(x, xs, ys) result(y)
    !===
        ! Linear interpolation, clamped at both ends. Guards the length-1
        ! case (constant series -- no file supplied) so it never divides
        ! by zero.
        implicit none
        real, intent(in) :: x
        real, intent(in) :: xs(:), ys(:)
        real :: y

        ! Local use only
        integer :: i, n

        n = size(xs)
        if (n == 1) then
            y = ys(1)
            return
        end if

        if (x <= xs(1)) then
            y = ys(1)
        else if (x >= xs(n)) then
            y = ys(n)
        else
            do i = 1, n-1
                if (x >= xs(i) .and. x <= xs(i+1)) then
                    y = ys(i) + (x-xs(i))/(xs(i+1)-xs(i))*(ys(i+1)-ys(i))
                    return
                end if
            end do
            y = ys(n) ! Unreachable given the bounds checks above
        end if
    end function interp1


end MODULE mo_const