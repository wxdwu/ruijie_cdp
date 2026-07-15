FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build \
    && if grep -R -n -E 'https?://(localhost|127\.0\.0\.1):8000' /app/dist; then \
         echo "ERROR: frontend contains a local API address" >&2; \
         exit 1; \
       fi

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
