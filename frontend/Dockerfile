FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html monte-carlo.html result.html styles.css menu.js form.js result.js /usr/share/nginx/html/

EXPOSE 80
