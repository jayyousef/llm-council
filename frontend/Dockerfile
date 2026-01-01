FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json /app/
RUN npm ci

COPY frontend /app
RUN npm run build

FROM nginx:alpine

# Put the nginx config template somewhere we control
COPY frontend/nginx.conf.template /etc/nginx/templates/nginx.conf.template

# Copy static build output
COPY --from=build /app/dist /usr/share/nginx/html

# Railway provides PORT; default to 80 for local runs
ENV PORT=80

# Render nginx config at runtime with env var substitution, then run nginx
CMD sh -c "envsubst '\$PORT' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"
