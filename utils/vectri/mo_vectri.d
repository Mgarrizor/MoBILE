build/mo_vectri.mod build/mo_vectri.o mo_vectri.o: src/mo_vectri.f90 \
build/mo_constants.o build/mo_methods.o build/mo_const.o
# Coupled builds only: mo_timestep USEs mo_vectri under #ifdef COUPLED
build/mo_timestep.o: build/mo_vectri.o
