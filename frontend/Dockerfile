FROM nginx:alpine

COPY frontend/static /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN chmod -R a+rX /usr/share/nginx/html \
    && chown -R nginx:nginx /usr/share/nginx/html

EXPOSE 80
