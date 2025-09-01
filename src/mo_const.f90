MODULE mo_const
  implicit none
! This module deals with array declarations, model parameters and the 
! selection of constants by disease case.
!
! Miguel Garrido Zornoza 2024 
! mgarrizoraca@gmail.com
!
! Index
!
! 1) Parameters
! 2) Cases
!    0 - Cholera
!    1 - Malaria (VECTRI) [non-functional]
!    2 - ??


! 1) Parameters ----------------------------------
    
    !********** Integration **********************
    integer :: nsteps       ! Number of integration steps (days) (either Namelist of Read from file)
    integer :: nagent       ! Number of agents
    real, allocatable    :: scale(:)   ! Scale factor to transform numbers into a densities
    real, allocatable    :: scaleI(:)  ! Inverse of scale
    !integer :: nalive       ! Number of alive agents
    real    :: dt = 1.      ! Time step (fixed)
    integer :: ncid_out     ! ID of output NetCDF file
    integer :: ncid_in      ! ID of input NetCDF files

    integer :: TempVarID, ncTempID
    integer :: RainVarID, ncRainID
    integer :: AreaVarID, ncAreaID


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
    integer, allocatable :: nattempt(:) ! Number of growth attempts in a given time step
    real, allocatable :: pop_dens(:)    ! 1D long array for human population density 
    real, allocatable :: Ipop_dens(:)   ! Inverse of 1D long array for human population density 
    real, allocatable :: D(:)           ! Dilution factor
    integer           :: P_a             ! Number of agents per person in the simulation
    real, allocatable :: A_cell(:)      ! Area of grid cells

    !********* Spin Up ***************************

    real :: SU_annual(365) ! Array with daily averages to test convergence
    logical :: SU_conv ! Convergende flag
    real :: SU_tol     ! Tolerance for convergence
    real :: SU_old     ! 

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

    integer, parameter :: K_h = 1000 

    real, allocatable, target :: S(:) ! 1D long array for Sensitive density
    real, allocatable, target :: E(:) ! 1D long array for Exposed density
    real, allocatable, target :: I(:) ! 1D long array for Infected density
    real, allocatable, target :: A(:) ! 1D long array for Asymptomatic density
    real, allocatable, target :: R(:) ! 1D long array for Recovered density

    type array_pointers
      real, pointer :: arr_p(:)
    end type array_pointers
    
    type(array_pointers) :: status_pointer(5)

    !--- Cholera ---
    real, allocatable :: B(:) ! 1D long array for Bacterial density
    real, allocatable :: F(:) ! 1D long array for Force of infection

    real, allocatable :: exc(:) ! 1D long array for the excretion events
    real, allocatable :: exc_clim(:) ! 1D long array for clim-driven excretion events

    real, allocatable :: B_old(:) !  
    real, allocatable :: A_old(:) ! 

    ! Cholera parameters 
    
    real :: mu_B, theta_e, theta_p, mu, rho, sigma, gamma, alpha, beta ! Disease
    real :: D_pop, H_0, D_grav, m       ! Pop. density and mobility
    real :: B_0, fS_0, fI_0, fA_0, fR_0 ! Initial conditions

    !--- Malaria ---

    real, allocatable :: EIR(:)   ! 1D long array for Entomological Inoculation Rate
    real, allocatable :: imm(:)   ! 1D long array for Endemicity level / Immunity
    ! Malaria parameters

    integer :: iip 
    real :: bite_night, bite_day        ! 
    real :: m_short, m_long             ! Fraction of short and long trip travellers
    real :: r_ret                       ! Time scale for long trip return home
    real :: fE_0                        ! Initial conditions

    real :: b_rate                      ! Mosquito biting rate (bites/mosquito/day)

    real :: e_0, e1, e2, A1, e_th, mat_rate ! Immunity - immunity acquisition parametrization
    real :: d_sig,d_mu,sig_1,mu_1         ! Immunity - clearance times parametrization
    real :: fA_chr                          ! Fraction of chronic asymptomatics
    integer :: tau_chr                      ! Duration of chronic parasitaemia
 
    real :: alph_max, alph_min          ! Symptomatics
    real :: sig_m, e_m

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
    real, allocatable :: m_0(:), m_1(:)  ! Vector to host ratio times the vector biting rate



    !********** Clima **************************
    real, allocatable :: rainfall(:,:)    ! 2D long array for rainfall (nxy,t)
    real, allocatable :: t2m(:,:)         ! 2D long array for temperature (nxy,t)

    real :: point_rain, point_temp

    !********** NetCDF **************************
    real                 :: fill_pop       !
    ! NetCDF IDs
    integer, allocatable :: VarId(:)
    integer :: DimId(3) = [1,2,3] !(lon,lat,time)
    integer :: Var3D
    ! Attribute list
    character(len=100), allocatable ::  att_list(:)     ! List of NetCDF file attributes (system params)


    CONTAINS

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
        m_short=0.6   ! Fraction of mobile population (could be an array to account for age, ... but is set to one constant for now)
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
        iip = 10              ! Intrinsic incubation period [day] Cowman et al 2016 [DOI:]
        bite_night = 0.       ! Base daily probability to get bitten overnight. Should be a function of wellfare index (availability of bednets, ...)
        bite_day   = 0.       ! Base daily probability to get bitten during day (relevant for short daily trips and vectors that are active during day hours)
        P_v0 = 0.3            ! Base vector to human transmission probability  Ermert et al. 2011 [DOI:]
        P_h0 = 0.2            ! Base human to vector transmission probability          "  "
        P_max= 0.2            ! Maximum transmission probability ~ 0.2 +- 0.15 Churcher et al. 2013 [DOI:]
                              !                                  ~ 0.125       Bousema  et al. 2011 [DOI:] ---> and references therein | Ouedraogo 2009 [DOI:]
                              !                                                                                                        | Schneider 2007 [DOI:]

        b_rate = 5            ! Vector biting rate - mean of 1.6 bites/person/hour from 18:00 - 6:30 (~ 1.6*12.5=20) Nzioki et al. 2023 [DOI:]

        mu  = 1./(61.*365)    ! Background human mortality rate [day^-1]

        ! Immunity

        e_0    = 0.09     ! Base increase in endemicity level [per infectious bite]                  [x]
        e1     = 0.5*e_0  ! e-folding factor in boosted maternal/naive immunity acquisition (fast) [e_0]
        e2     = 10*e_0   ! e-folding factor in gradual immunity acquisition (slow)                [e_0]
        A1     = 0.9      ! Coefficient weighting each time scale
        e_th   = 0.001    ! Threshold endemicity level value for R --> S transition                  [x]

        mat_rate = log(2.)/(6.*30)  ! Loss rate of maternal immunity = ln(2)/(Half-life of maternal immunity) [day^-1] (~ 6 months)
                                  !
                                  ! 3-9 months Gupta 1999 [DOI:]
                                  ! 3   months Ghani 2009 [DOI:]
        rho = log(2.)/(6.*365)    ! Decay rate of endemicity/immunity level = ln(2)/(Half-life of clinical immunity) 5   [yr] Filipe 2007 [DOI:]
                                  !                                                                                  6.9 [yr] Ghani 2009  [DOI:]
        !-- Clearance times       ! The reported mean and std are those of the corresponding normal distribution.
        d_mu    = -3.54           ! mu_1 = 5.2  (MT (PfPR ~ 0 %) [Sama et al. 2006a]), mu_2 = 1.66 (Ghana (PfPR ~ 75%) [Bretscher et al. 2011])
        d_sig   =  0.47           ! sig1 = 0.73 (MT (PfPR ~ 0 %) [Sama et al. 2006a]), sig2 = 1.20 (Ghana (PfPR ~ 75%) [Bretscher et al. 2011])
        sig_1   =  0.73           ! 
        mu_1    =  5.2            !

        ! Symptomatics 
                          ! These values are only relevant when 
        fA_chr   = 0.05   ! Fraction of chronic asymptomatics [unkown]
        tau_chr  = 365    ! Duration of chronic parasitaemia  [unkown]
                          ! 
        alph_min = 0.28   !    We take the lowest we can find from literature focusing on highly endemic areas reporting adult prevalence
                          !    1-0.311 (Malawi) Topazian    2020 [DOI:]
                          !    1-0.482 (DCR)    Mvumbi      2015 [DOI:]
                          !    1-0.520 (Gabon)  Dal-Bianco  2007 [DOI:]
                          !    1-0.680 (Ghana)  Heinemann   2020 [DOI:]
        ! So far this one ---> 1-0.721 (Ghana)  Owusu-Agyei 2002 [DOI:] 
        alph_max = 1.    !

        sig_m  = 20.     ! Sigmoidal curve param ~ slope
        e_m    = 0.35    ! Sigmoidal curve param ~ inflection point

        ! Mobility ---------------------------------------------------

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


end MODULE mo_const