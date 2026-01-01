FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json /app/
RUN npm ci

COPY frontend /app
RUN npm run build

FROM nginx:alpine

# Put the nginx config template somewhere we control
COPY frontend/nginx.conf.template /etc/nginx/templates/nginx.conf.template
COPY frontend/config.js.template /etc/nginx/templates/config.js.template

# Copy static build output
COPY --from=build /app/dist /usr/share/nginx/html

# Railway provides PORT; default to 80 for local runs
ENV PORT=80

# Render nginx config + runtime config at container start, then run nginx
CMD sh -c "set -eu; : \"${VITE_API_BASE_URL:?VITE_API_BASE_URL is required (e.g. https://your-backend.up.railway.app)}\"; envsubst '\$PORT' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf; envsubst '\$VITE_API_BASE_URL' < /etc/nginx/templates/config.js.template > /usr/share/nginx/html/config.js; nginx -g 'daemon off;'"
