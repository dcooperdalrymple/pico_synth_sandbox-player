DEVICE := /media/$(USER)/CIRCUITPY/
ifeq ($(wildcard $(DEVICE).),)
	DEVICE := /run/media/$(USER)/CIRCUITPY/
endif

SRCS := code.py \
		lib/umidiparser.py

all: upload requirements

upload: $(SRCS)
	@for file in $^ ; do \
		echo $${file} "=>" $(DEVICE)$${file} ; \
		cp $${file} $(DEVICE)$${file} ; \
	done
