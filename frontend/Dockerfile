# Frontend image: compile the SPA with pnpm, then serve the static files with nginx.
#
# The API origin is baked in at build time because the browser (not the container) calls the
# backend. Pass it as a build arg; changing it requires rebuilding the image.
# The build stage tag is pinned deliberately so a floating tag cannot silently ship an older,
# vulnerable Node patch. Bump it together with Node security releases.
FROM node:26.12.1-alpine AS build

WORKDIR /app

RUN npm install --global pnpm@12.14.0

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm build

FROM nginx:1.27-alpine AS runtime

# Client-side routes need index.html for paths nginx does not find on disk.
RUN printf '%s\n' \
    'server {' \
    '    listen 8080;' \
    '    server_name _;' \
    '    root /usr/share/nginx/html;' \
    '    index index.html;' \
    '    location / {' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '}' \
    > /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
