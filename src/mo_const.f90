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
    real    :: scale        ! Scale factor to transform numbers into a densities
    real    :: scaleI       ! Inverse of scale
    integer :: nalive       ! Number of alive agents
    real    :: dt = 1.      ! Time step (fixed)
    integer :: ncid_out     ! ID of output NetCDF file
    integer :: ncid_in      ! ID of input NetCDF files

    integer :: TempVarID, ncTempID
    integer :: RainVarID, ncRainID


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
    

    !********** Grid *****************************
    integer :: nlon  ! Number of longitude points
    integer :: nlat  ! Number of latitude points
    integer :: nxy   ! Number of lattice points (=nlat*nlon)
    integer :: ntime ! Number of time steps in forcing input data

    real    :: dx  ! Horizontal discretization
    real    :: dy  ! Vertical discretization

    integer :: seed=1234           ! 
    integer :: spin_up=0           ! Spin up time [days]

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

    real, allocatable :: S(:) ! 1D long array for Sensitive density
    real, allocatable :: E(:) ! 1D long array for Exposed density
    real, allocatable :: I(:) ! 1D long array for Infected density
    real, allocatable :: A(:) ! 1D long array for Asymptomatic density
    real, allocatable :: R(:) ! 1D long array for Recovered density

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


    ! Malaria parameters

    integer :: iip 
    real :: bite_night, bite_day        ! 
    real :: m_short, m_long             ! Fraction of short and long trip travellers
    real :: r_ret                       ! Time scale for long trip return home
    real :: fE_0                        ! Initial conditions

    real :: e_0, tau_e1, tau_e2, e_th   ! Immunity
 
    real :: alph_max, alph_min          ! Symptomatics

    !--- VECTRI/Malaria ---
    ! mo_vectri.f90
    integer, allocatable :: nbites(:)       ! (nlon*nlat) Infective bites
                                            ! (vectors that were infected upon
                                            ! bitting a human)
    real, allocatable :: rgonof(:)          ! Gonotrophic cycle 

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
        rho  =1./(3.*365) ! Lost of immunity rate                  [day^-1]
        sigma=0.2         ! Proportion of symptomatics             [fraction]
        gamma=0.2         ! Recovery rate                          [day^-1]
        alpha=0.004       ! Death rate (infection or other causes) [day^-1]
        !    
        ! Mobility ---------------------------------------------------
        m_short=0.6      ! Fraction of mobile population (could be an array to account for age, ... but is set to one constant for now)
        D_grav=2.   ! e-folding distance for gravity model [km] ; Rinaldo et al. (2012) gives 100km for Haiti's epidemic
        beta=1.    ! Contact rate [day^-1]
        
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
        iip = 15              ! Intrinsic incubation period [day] [ref:??]
        bite_night = 0.       ! Base daily probability to get bitten overnight. Should be a function of wellfare index (availability of bednets, ...)
        bite_day   = 0.       ! Base daily probability to get bitten during day (relevant for short daily trips and vectors that are active during day hours)

        mu   =1./(61.*365)! Background human mortality rate        [day^-1]
        rho  =1./(3.*365) ! Lost of immunity rate                  [day^-1]

        ! Immunity

        e_0    = 0.01     ! Base increase in endemicity level [per infectious bite]               [x]
        tau_e1 = 2*e_0    ! e-folding decay in boosted maternal/naive immunity acquisition (fast) [e_0]
        tau_e2 = 100*e_0  ! e-folding decay in gradual immunity acquisition (slow)                [e_0]
        e_th   = 0.001    ! Threshold endemicity level value for R --> S transition               [x]

        ! Symptomatics 

        alph_min = 0.25   ! []
        alph_max = 1.     !


        ! Mobility ---------------------------------------------------

        m_short=0.6   ! Fraction of mobile population making short daily trips (could be an array to account for age, ... but is set to one constant for now)
        m_long =1.e-3 ! Fraction of mobile population starting long overnight trips
        r_ret  =1./5. ! Rate of long trip return
        D_grav =2.    ! e-folding distance for gravity model [km] 
        beta   =1.    ! Contact rate 

        ! Idealized world parameters
        D_pop=10   ! e-folding decay for radial city         [km]
        H_0=2000   ! Human population density at city centre [km^2]

        ! Default initial conditions ---------------------------------
        
        fS_0=1.   ! Susceptible  [fraction]
        fE_0=0.   ! Infected     [fraction]
        fI_0=0.   ! Asymptomatic [fraction]
        fR_0=0.   ! Recovered    [fraction]

        ! Attribute list 
        !att_list = ['m_short','m_long', 'bite_night']

      case(2)
        disease_name="Malaria"

      case default
        print *, "Incorrect case, choose disID between: 0 (cholera) and 1 (malaria)"
        STOP
      end SELECT

      print *, "Disease: ", disease_name
    end subroutine const_disease


end MODULE mo_const