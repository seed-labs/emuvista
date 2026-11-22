FROM solidnerd/bookstack:26.9.3

# SEED configures routes before dropping back to the upstream application user.
USER root
RUN sed -i 's/8080/80/g' /etc/apache2/ports.conf /etc/apache2/sites-available/000-default.conf
EXPOSE 80
