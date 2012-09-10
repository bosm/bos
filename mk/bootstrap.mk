-include bdeps.mk

E := ${BOS_TOPDIR}/bos/exe/
bos_statedir := $(CURDIR)/states/

.PHONY: all bootstrap

all: .bootstrap
	@:

bootstrap .bootstrap: ${BOS_TOPDIR}distro/config/arch ${BOS_TOPDIR}distro/config/packages .rebootstrap
	@$(E)boslog -d "bootstrapping build system ..."
	@mkdir -p $(bos_statedir)
	@$(E)bosbootstrap && echo -n "${BOS_TOPDIR}" > .bootstrap
	@$(E)boslog -d "boostrap completed."
