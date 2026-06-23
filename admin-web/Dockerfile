FROM node:25-alpine AS build

WORKDIR /app
COPY admin-web/package*.json ./
RUN npm ci
COPY admin-web/tsconfig.json admin-web/vite.config.ts ./
COPY admin-web/shared ./shared
COPY admin-web/customer-admin ./customer-admin
COPY admin-web/system-admin ./system-admin
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
