MODULE mo_spinup
! This module contains spin-up methods
! to deal with the slow adjustment of
! immunity.

! Author: Miguel Garrido Zornoza (2025)
! Contact: mgarrizoraca@gmail.com

  USE mo_const, only: nxy, nsteps, t2m, rainfall

implicit none

  integer, parameter :: ndays_year = 365
  integer, parameter :: max_clim_years = 5   ! Cap on years averaged into the spin-up climatology

  ! Aliases to the real driver record (set by build_spinup_climatology,
  ! consumed by restore_spinup_forcing) and the climatological year that
  ! t2m/rainfall are redirected to during spin-up.
  real, pointer :: t2m_real(:,:) => null(), rainfall_real(:,:) => null()
  real, pointer :: t2m_clim(:,:) => null(), rainfall_clim(:,:) => null()

CONTAINS

! Build a day-of-year climatology (averaged over up to max_clim_years
! complete years at the start of the driver record) and point t2m/rainfall
! at it, so the existing spin-up loop (itime=1,365 in mobile.f90) integrates
! against a typical seasonal cycle instead of replaying the raw first year (previous version).
! Call restore_spinup_forcing() to swap the real record back in afterwards.
subroutine build_spinup_climatology()

    implicit none

    integer :: nyears_avail, nyears_use, iy, id, idx

    nyears_avail = nsteps / ndays_year
    if (nyears_avail < 1) then
        print *, 'Cannot build spin-up climatology: less than 1 full year of driver data --> Exit'
        STOP
    end if
    nyears_use = min(nyears_avail, max_clim_years)

    allocate(t2m_clim(nxy,ndays_year))
    allocate(rainfall_clim(nxy,ndays_year))
    t2m_clim(:,:)      = 0.
    rainfall_clim(:,:) = 0.

    do iy = 0, nyears_use - 1
        do id = 1, ndays_year
            idx = iy*ndays_year + id
            t2m_clim(:,id)      = t2m_clim(:,id)      + t2m(:,idx)
            rainfall_clim(:,id) = rainfall_clim(:,id) + rainfall(:,idx)
        end do
    end do

    t2m_clim(:,:)      = t2m_clim(:,:)      / real(nyears_use)
    rainfall_clim(:,:) = rainfall_clim(:,:) / real(nyears_use)

    print '("Spin-up climatology built from ",i2," year(s) (cap = ",i2,").")', nyears_use, max_clim_years

    ! Alias the real record, then redirect t2m/rainfall to the climatology
    t2m_real      => t2m
    rainfall_real => rainfall
    t2m           => t2m_clim
    rainfall      => rainfall_clim

end subroutine build_spinup_climatology

! Swap t2m/rainfall back to the real driver record and free the
! climatology arrays built by build_spinup_climatology().
subroutine restore_spinup_forcing()

    implicit none

    t2m      => t2m_real
    rainfall => rainfall_real
    nullify(t2m_real, rainfall_real)
    deallocate(t2m_clim, rainfall_clim)

end subroutine restore_spinup_forcing

! Direct integration
subroutine DI(x_new,x_old,tol_SU,conv)

    implicit none

    real, allocatable, intent(inout) :: x_new(:) ! Array with values averaged over the whole spatial domain (daily time step)
    real, allocatable, intent(inout) :: x_old(:) ! Array with values averaged over the whole spatial domain (daily time step)
    real, intent(in) :: tol_SU                   ! Tolerance of convergence
    logical, intent(out) :: conv                 ! Convergence boolean

    ! Local use only
    real :: eps_SU   ! Epsilon Spin-Up
    integer :: n 
    real :: dummy(size(x_new))

    n = size(x_new)
    dummy(:) = 0.
    if (n /= 0) then
        n = count(mask=(x_new(:) > 0.))
        where (x_new(:) > 0.)
            dummy(:) = abs(x_new(:)-x_old(:))!/x_new(:)     ! Supressed relative deviation since it blows up (low numbers + stochasticity)
        end where
        !
        eps_SU = sum(dummy(:))/n!*100 ! Deviation expressed in percentage
        !
        WRITE(*,'(1a1,A20,F6.4,A5,F6.4)', advance='no') char(13),'Spin-up convergence ',eps_SU,' <=? ',tol_SU
        print *, sum(x_new(:)), sum(x_old(:))
    else 
        print*, 'Cannot compute mean during Spin-up --> Exit'
        STOP
    end if
    !
    if (eps_SU <= tol_SU) then
        conv = .true.
    end if
    !
end subroutine DI

! Anderson acceleration method
subroutine AA()
    ! https://www.youtube.com/watch?v=fU_Ey5haF_M 
    ! Problem is the convergence is measured on a diagnostic variable (year and grid average of immunity level)
    ! instead of the prognostic imm of each agent. How do we deal with this?
    ! Should we look for explicit convergence of each imm attribute?

    implicit none

end subroutine AA


end MODULE mo_spinup