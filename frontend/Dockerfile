FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html monte-carlo.html result.html asset-inventory.html vulnerability-database.html styles.css menu.js form.js result.js inventory.js vulnerability.js /usr/share/nginx/html/

EXPOSE 80
