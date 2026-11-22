FROM handsonsecurity/seedemu-base:2.0
RUN printf '%s\n' \
      'slapd slapd/no_configuration boolean false' \
      'slapd slapd/domain string company.com' \
      'slapd shared/organization string Company' \
      'slapd slapd/password1 password DirectoryAdminDemo123!' \
      'slapd slapd/password2 password DirectoryAdminDemo123!' \
      'slapd slapd/backend select MDB' | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils python3 python3-ldap \
    && rm -rf /var/lib/apt/lists/* \
    && service slapd stop \
    && mkdir -p /opt/identity-ldap \
    && cp -a /etc/ldap/slapd.d /opt/identity-ldap/config \
    && cp -a /var/lib/ldap /opt/identity-ldap/data
COPY directory-start /usr/local/bin/directory-start
RUN chmod +x /usr/local/bin/directory-start
CMD ["/usr/local/bin/directory-start"]
