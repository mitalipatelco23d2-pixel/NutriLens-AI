FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
ARG PUBLIC_WEBSITE_URL=http://localhost:3000
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID=
ARG NEXT_PUBLIC_SUPPORT_EMAIL=
ENV NEXT_OUTPUT_MODE=standalone \
    PUBLIC_WEBSITE_URL=${PUBLIC_WEBSITE_URL} \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_GOOGLE_CLIENT_ID=${NEXT_PUBLIC_GOOGLE_CLIENT_ID} \
    NEXT_PUBLIC_SUPPORT_EMAIL=${NEXT_PUBLIC_SUPPORT_EMAIL}
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 10001 nutrilens \
    && adduser --system --uid 10001 --ingroup nutrilens nutrilens
COPY --chown=nutrilens:nutrilens --from=build /app/.next/standalone ./
COPY --chown=nutrilens:nutrilens --from=build /app/.next/static ./.next/static
COPY --chown=nutrilens:nutrilens --from=build /app/public ./public
EXPOSE 3000
USER nutrilens
CMD ["node", "server.js"]
