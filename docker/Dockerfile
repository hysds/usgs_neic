FROM hysds/pge-base:latest

MAINTAINER jlinick "Justin.P.Linick@jpl.nasa.gov"
LABEL description="USGS NEIC query & evaluation base image"

#install shapely for client side filtering
USER root
RUN pip install shapely

USER ops
# copy packages
COPY . /home/ops/verdi/ops/usgs_neic
RUN set -ex \
 && source /home/ops/verdi/bin/activate \
 && sudo chown -R ops:ops /home/ops/verdi/ops/usgs_neic

WORKDIR /home/ops
CMD ["/bin/bash", "--login"]
