FROM public.ecr.aws/lambda/python:3.8 AS sc_monolith_1

LABEL maintainer="Casey Slaught <casey@smartcarte.earth>"
LABEL authors="Casey Slaught <casey@smartcarte.earth>"

# install system libraries
RUN \
    yum makecache fast; \
    yum install -y gcc gcc-c++ openssl-devel; \
    yum install -y libtiff-devel libjpeg-devel bzip2; \ 
    yum install -y flex flex-devel bison bison-devel byacc; \
    yum install -y wget libpng-devel nasm rsync; \
    yum install -y tar.x86_64 make;  \
    yum install -y cmake3; \
    yum install -y bash-completion --enablerepo=epel; \
    yum install -y perl-core zlib-devel; \
    yum clean all; \
    yum autoremove

# versions of packages
ENV \
    GDAL_VERSION=3.2.1 \
    PROJ_VERSION=7.2.1 \
    GEOS_VERSION=3.8.1 \
    GEOTIFF_VERSION=1.6.0 \
    HDF4_VERSION=4.2.15 \
    HDF5_VERSION=1.10.7 \
    NETCDF_VERSION=4.7.4 \
    NGHTTP2_VERSION=1.41.0 \
    OPENJPEG_VERSION=2.4.0 \
    LIBJPEG_TURBO_VERSION=2.0.6 \
    CURL_VERSION=7.73.0 \
    PKGCONFIG_VERSION=0.29.2 \
    SZIP_VERSION=2.1.1 \
    WEBP_VERSION=1.1.0 \
    ZSTD_VERSION=1.4.5

# paths to things
ENV \
    BUILD=/build \
    NPROC=4 \
    PREFIX=/usr/local \
    GDAL_CONFIG=/usr/local/bin/gdal-config \
    LD_LIBRARY_PATH=/usr/local/lib:/usr/local/lib64 \
    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/lib64/pkgconfig \
    GDAL_DATA=/usr/local/share/gdal \
    PROJ_LIB=/usr/local/share/proj

ENV LD_LIBRARY_PATH=$PREFIX/lib:$PREFIX/lib64:$LD_LIBRARY_PATH
ENV PATH=$PREFIX/bin/:$PATH

# switch to a build directory
WORKDIR ${BUILD}


FROM sc_monolith_1 as sc_monolith_2


# Open SSL
#RUN \
#    mkdir openssl; \
#    wget -qO- https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz \
#        | tar xvz -C openssl --strip-components=1; cd openssl; \
#    ./config shared --prefix=${PREFIX}/openssl --openssldir=${PREFIX}/openssl; \
#    make depend; make -j ${NPROC} install; \
#    cd ${BUILD};    
# rm -rf openssl;

# nghttp2
RUN \
    mkdir nghttp2; \
    wget -qO- https://github.com/nghttp2/nghttp2/releases/download/v${NGHTTP2_VERSION}/nghttp2-${NGHTTP2_VERSION}.tar.gz \
        | tar xvz -C nghttp2 --strip-components=1; cd nghttp2; \
    ./configure --enable-lib-only --prefix=${PREFIX}; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf nghttp2;


# curl
RUN \
    mkdir curl; \
    wget -qO- https://curl.haxx.se/download/curl-${CURL_VERSION}.tar.gz \
        | tar xvz -C curl --strip-components=1; cd curl; \
    ./configure --prefix=${PREFIX} --disable-manual --disable-cookies --with-nghttp2=${PREFIX} --with-ssl; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf curl;

# pkg-config - version > 2.5 required for GDAL 2.3+
RUN \
    mkdir pkg-config; \
    wget -qO- https://pkg-config.freedesktop.org/releases/pkg-config-$PKGCONFIG_VERSION.tar.gz \
        | tar xvz -C pkg-config --strip-components=1; cd pkg-config; \
    ./configure --prefix=$PREFIX --with-internal-glib CFLAGS="-O2 -Os"; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf pkg-config;


# sqlite3 (required by proj)
RUN \
    mkdir sqlite3; \
    wget -qO- https://www.sqlite.org/2020/sqlite-autoconf-3330000.tar.gz \
        | tar xvz -C sqlite3 --strip-components=1; cd sqlite3; \
    ./configure --prefix=$PREFIX; \
    make; make install; \
    cd ${BUILD}; rm -rf sqlite3;


FROM sc_monolith_2 as sc_monolith_3


# proj
RUN \
    mkdir proj; \
    wget -qO- http://download.osgeo.org/proj/proj-$PROJ_VERSION.tar.gz \
        | tar xvz -C proj --strip-components=1; cd proj; \
    SQLITE3_LIBS="=L$PREFIX/lib -lsqlite3" SQLITE3_INCLUDE_DIRS=$PREFIX/include/proj \
        ./configure --prefix=$PREFIX; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf proj;


# GEOS
RUN \
    mkdir geos; \
    wget -qO- http://download.osgeo.org/geos/geos-$GEOS_VERSION.tar.bz2 \
        | tar xvj -C geos --strip-components=1; cd geos; \
    ./configure --enable-python --prefix=$PREFIX CFLAGS="-O2 -Os"; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf geos;


# ZSTD
RUN \
    mkdir zstd; \
    wget -qO- https://github.com/facebook/zstd/archive/v${ZSTD_VERSION}.tar.gz \
        | tar -xvz -C zstd --strip-components=1; cd zstd; \
    make -j ${NPROC} install PREFIX=$PREFIX ZSTD_LEGACY_SUPPORT=0 CFLAGS=-O1 --silent; \
    cd ${BUILD}; rm -rf zstd;


# geotiff
RUN \
    mkdir geotiff; \
    wget -qO- https://download.osgeo.org/geotiff/libgeotiff/libgeotiff-$GEOTIFF_VERSION.tar.gz \
        | tar xvz -C geotiff --strip-components=1; cd geotiff; \
    ./configure --prefix=${PREFIX} \
        --with-proj=${PREFIX} --with-jpeg=${PREFIX} --with-zip=yes;\
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf geotiff;


FROM sc_monolith_3 as sc_monolith_4


# GDAL
RUN \
    mkdir gdal; \
    wget -qO- http://download.osgeo.org/gdal/$GDAL_VERSION/gdal-$GDAL_VERSION.tar.gz \
        | tar xvz -C gdal --strip-components=1; cd gdal; \
    ./configure \
        --disable-debug \
        --disable-static \
        --prefix=${PREFIX} \
        --with-geotiff=${PREFIX} \
        --with-zstd=${PREFIX} \
        --with-threads=yes \
        --with-sqlite3=${PREFIX} \
        --with-curl=${PREFIX}/bin/curl-config \
        --with-python \
        --without-libtool \
        --disable-driver-elastic \
        --with-geos=${PREFIX}/bin/geos-config \
        --with-hide-internal-symbols=yes \
        CFLAGS="-O2 -Os" CXXFLAGS="-O2 -Os" \
        LDFLAGS="-Wl,-rpath,'\$\$ORIGIN'"; \
    make -j ${NPROC} install; \
    cd ${BUILD}; rm -rf gdal;


FROM sc_monolith_4 as sc_monolith_5


COPY requirements*.txt ./

RUN \
    pip install -r requirements-pre.txt; \
    pip install -r requirements.txt; \
    pip install GDAL==${GDAL_VERSION}; \
    pip install matplotlib; 


FROM sc_monolith_5 as sc_monolith_6


COPY src ${LAMBDA_TASK_ROOT}/src

COPY .aws /root/.aws

WORKDIR ${LAMBDA_TASK_ROOT}/src

ENTRYPOINT [ "python", "-u", "handler.py" ]
