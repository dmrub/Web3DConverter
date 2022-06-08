FROM ubuntu:20.04
LABEL org.opencontainers.image.authors="Dmitri Rubinstein <dmitri.rubinstein@dfki.de>"

RUN set -xe; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update -y; \
    apt-get install -y --no-install-recommends \
        build-essential git cmake pkg-config zlib1g-dev \
        libpng-dev libjpeg-dev libboost-thread-dev curl unzip \
        python3 python3-pip; \
    pip install --upgrade pip;

# Prepare development environment

RUN mkdir -p /usr/src
WORKDIR /usr/src

# Build LDRConverter

COPY LDRConverter /usr/src/LDRConverter

WORKDIR /usr/src/LDRConverter

RUN cmake -DCMAKE_INSTALL_PREFIX:PATH=/usr CMakeLists.txt -G 'Unix Makefiles' && make && make install

# Download ldraw to /usr/share/ldraw

COPY download-ldraw-lib.sh /tmp/ldcad/download-ldraw-lib.sh
RUN set -xe;  \
    chmod +x /tmp/ldcad/download-ldraw-lib.sh; \
    mkdir -p /usr/share; \
    cd /usr/share; \
    /tmp/ldcad/download-ldraw-lib.sh; \
    rm /tmp/ldcad/download-ldraw-lib.sh

ENV LDRAWDIR=/usr/share/ldraw

# Build assimp

COPY assimp /usr/src/assimp

WORKDIR /usr/src/assimp

RUN cmake -DCMAKE_INSTALL_PREFIX:PATH=/usr CMakeLists.txt -G 'Unix Makefiles' && make && make install

# Build Web LDR Converter

RUN mkdir -p /usr/src/WebLDRConverter

COPY app /usr/src/WebLDRConverter/app
COPY run.py /usr/src/WebLDRConverter/run.py
COPY requirements.txt /usr/src/WebLDRConverter/requirements.txt
COPY LICENSE /usr/src/WebLDRConverter/LICENSE

WORKDIR /usr/src/WebLDRConverter

RUN pip install -r requirements.txt

ENTRYPOINT ["/usr/src/WebLDRConverter/run.py"]
