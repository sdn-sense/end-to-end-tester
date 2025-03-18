FROM almalinux:9

# hadolint ignore=DL3033
RUN yum -y install wget epel-release && yum clean all

# Maria DB Configuration
COPY build_files/mariadb.repo /etc/yum.repos.d/mariadb.repo
COPY build_files/mariadb.sql /root/mariadb.sql
COPY build_files/server.cnf /etc/my.cnf.d/server.cnf
# Import GPG Keys for MariaDB and EPEL
WORKDIR /etc/pki/rpm-gpg/
RUN wget --progress=dot:giga https://yum.mariadb.org/RPM-GPG-KEY-MariaDB && rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-MariaDB

RUN adduser mysql -U -u 4000
RUN mkdir -p /var/log/mariadb/ && mkdir -p /opt/end-to-end-tester/mysql/ && \
    mkdir -p /var/log/EndToEndTester && mkdir -p /var/log/supervisor && mkdir -p /etc/supervisord.d/ && \
    chown mysql:mysql /var/log/mariadb/ && \
    chown mysql:mysql /opt/end-to-end-tester/mysql/ && \
    mkdir -p /opt/end-to-end-tester/outputfiles/archived/

# hadolint ignore=DL3033
RUN yum -y install git cronie python3.12-devel python3.12-pip python3.12 python3-pyOpenSSL python3.12-PyMySQL fetch-crl MariaDB-server MariaDB-client MariaDB-shared MariaDB-devel gcc && yum clean all
# Set python3.12 as default
RUN alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 100 && \
    alternatives --set python3 /usr/bin/python3.12
# Install all pip packages

# hadolint ignore=DL3013
RUN pip3.12 install --no-cache-dir --upgrade setuptools pip && \
    pip3.12 install --no-cache-dir supervisor superlance mariadb

# Upgrade PIP SetupTools and wheek and Install SENSE Py Client
WORKDIR /opt/sense-o-py-client
RUN git clone https://github.com/sdn-sense/sense-o-py-client.git . && \
    pip3 install --no-cache-dir -r requirements.txt && pip3 install --no-cache-dir .

WORKDIR /opt/code
RUN git clone https://github.com/sdn-sense/end-to-end-tester.git . && \
    pip3 install --no-cache-dir -r requirements.txt && pip3 install --no-cache-dir .


# Install crons to fetch CA Certs
COPY build_files/etc/cron.d/fetch-crl /etc/cron.d/fetch-crl
COPY build_files/etc/cron.d/fetch-crl-reboot /etc/cron.d/fetch-crl-reboot
# Install Supervisord files
COPY build_files/etc/supervisord.conf /etc/
COPY build_files/etc/supervisord.d/01-mariadb.conf /etc/supervisord.d/
COPY build_files/etc/supervisord.d/02-EndToEndWorker.conf /etc/supervisord.d/
COPY build_files/etc/supervisord.d/03-mariadbstart.conf /etc/supervisord.d/
# Install local scripts
COPY build_files/usr/local/sbin/dbstart.sh /usr/local/sbin/dbstart.sh
COPY build_files/usr/local/sbin/dbstart.py /usr/local/sbin/dbstart.py
COPY build_files/usr/local/sbin/mariadb.sh /usr/local/sbin/mariadb.sh
COPY build_files/usr/local/sbin/dbrecorder.py /usr/local/sbin/dbrecorder.py
COPY build_files/usr/local/sbin/endtester.py /usr/local/sbin/endtester.py
# Install mysql sql file (for startup)
COPY build_files/root/mariadb.sql /root/mariadb.sql

# Install CA Certs
RUN rpm -i https://repo.opensciencegrid.org/osg/24-main/el9/release/x86_64/Packages/o/osg-ca-certs-1.134-1.osg24.el9.noarch.rpm
# Install InCommon Server CA 2
RUN wget -O /etc/grid-security/certificates/InCommon_RSA_Server_CA_2.pem --progress=dot:giga "https://spaces.at.internet2.edu/download/attachments/24576265/InCommon%20RSA%20Server%20CA%202.pem?api=v2" && \
    ln -s /etc/grid-security/certificates/InCommon_RSA_Server_CA_2.pem /etc/grid-security/certificates/$(openssl x509 -in /etc/grid-security/certificates/InCommon_RSA_Server_CA_2.pem -noout -hash).0

WORKDIR /opt/

CMD ["/usr/local/bin/supervisord", "-c", "/etc/supervisord.conf"]
