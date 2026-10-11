import importlib, sys
packages = {
    shapely: shapely,
    pyproj: pyproj,
    polyline: polyline,
    h3: h3,
    psycopg: psycopg,
    pydantic_settings: pydantic-settings,
    ollama: ollama,
    gpxpy: gpxpy,
    mutagen: mutagen,
    sentry_sdk: sentry-sdk,
    elevenlabs: elevenlabs,
    respx: respx,
    langgraph_checkpoint_postgres: langgraph-checkpoint-postgres,
}
missing = []
for mod_name, pip_name in packages.items():
    try:
        m = importlib.import_module(mod_name)
        ver = getattr(m, __version__, ok)
        print(fFOUND
