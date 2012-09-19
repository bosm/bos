-include deps.mk

E := ${BOS_TOPDIR}/bos/exe/
bos_statedir := $(CURDIR)/states/
bos_toolchain_packages := $(shell cat toolchain-packages 2>/dev/null)
bos_packages := $(shell cat packages 2>/dev/null)

bos_all_packages := $(bos_toolchain_packages) $(bos_packages)

all: $(addsuffix .d,$(addprefix $(bos_statedir),$(bos_all_packages)))
	@:

clean: $(addsuffix -clean,$(bos_all_packages))

.PHONY: $(bos_all_packages)
$(bos_packages): $(bos_toolchain_packages)

$(bos_all_packages):
	@$(E)boslog -d "main.mk: building $@"
	@$(E)bosprepare $@
	@$(E)bosconfig $@
	@$(E)boscompile $@
	@$(E)bosinstall $@

$(addsuffix -prepare,$(bos_all_packages)):
	@$(E)boslog -d "main.mk: preparing ${subst -prepare,, $(@F)}."
	@$(E)bosprepare ${subst -prepare,, $(@F)}

$(addsuffix -config,$(bos_all_packages)):
	@$(E)boslog -d "main.mk: configuring ${subst -config,, $(@F)}."
	@$(E)bosconfig ${subst -prepare,, $(@F)}

$(addsuffix -compile,$(bos_all_packages)):
	@$(E)boslog -d "main.mk: compiling ${subst -compile,, $(@F)}."
	@$(E)boscompile ${subst -compile,, $(@F)}

$(addsuffix -install,$(bos_all_packages)):
	@$(E)boslog -d "main.mk: installing ${subst -install,, $(@F)}."
	@$(E)bosinstall ${subst -install,, $(@F)}

$(addsuffix -clean,$(bos_all_packages)):
	@$(E)boslog -d "main.mk: cleaning $(@F)."
	@$(E)bosclean ${subst -clean,, $(@F)}

.PHONY: bootstrap
bootstrap:
	@$(MAKE) -f ${BOS_TOPDIR}/bos/mk/bootstrap.mk $@

$(addsuffix .p,$(addprefix $(bos_statedir),$(bos_all_packages))): .rebuild
	@$(E)boslog -d "main.mk: preparing ${subst .p,, $(@F)} as dependency."
	@$(E)bosprepare ${subst .p,, $(@F)}

$(addsuffix .f,$(addprefix $(bos_statedir),$(bos_all_packages))): %.f: %.p
	@$(E)boslog -d "main.mk: configuring ${subst .f,, $(@F)} as dependency."
	@$(E)bosconfig ${subst .f,, $(@F)}

$(addsuffix .b,$(addprefix $(bos_statedir),$(bos_all_packages))): %.b: %.f
	@$(E)boslog -d "main.mk: compiling ${subst .b,, $(@F)} as dependency."
	@$(E)boscompile ${subst .b,, $(@F)}

$(addsuffix .d,$(addprefix $(bos_statedir),$(bos_all_packages))): %.d: %.b
	@$(E)boslog -d "main.mK: installing ${subst .d,, $(@F)} as dependency."
	@$(E)bosinstall ${subst .d,, $(@F)}
