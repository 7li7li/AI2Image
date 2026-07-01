export function normalizeAppPath(pathname: string) {
  return pathname.replace(/\/+$/, "") || "/";
}

export function getRouteHref(pathname: string) {
  const normalizedPathname = normalizeAppPath(pathname);
  return normalizedPathname === "/" ? normalizedPathname : `${normalizedPathname}/`;
}
