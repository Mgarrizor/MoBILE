build/mo_methods.mod build/mo_methods.o mo_methods.o: src/mo_methods.f90 \
build/mo_constants.o build/mo_advect.o
# mo_advect USEs mo_constants
build/mo_advect.o: build/mo_constants.o
