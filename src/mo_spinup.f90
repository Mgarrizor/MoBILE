MODULE mo_spinup
! This module contains spin-up methods
! to deal with the slow adjustment of 
! immunity.

! Author: Miguel Garrido Zornoza (2025)
! Contact: mgarrizoraca@gmail.com


implicit none

CONTAINS 

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