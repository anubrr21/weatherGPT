import asyncio, json
from app.services import weather, alerts, tools, agent

async def main():
    ctx = tools.ChatContext(lat=16.5062, lon=80.648, language="en")
    fc = await tools.get_forecast(ctx)
    print("FORECAST", fc["place"], fc["now"])
    al = await tools.get_alerts(ctx, "Bardhaman")
    print("ALERTS", al["place"], len(al["official_imd_ndma_alerts"]), [a["headline"][:80] for a in al["official_imd_ndma_alerts"][:2]], al["model_derived_advisories"][:2])
    aq = await tools.get_air_quality(ctx, "Delhi")
    print("AIR", aq["place"], aq["india_naqi"], aq["india_naqi_band"])
    cl = await tools.get_climate(ctx, month=9)
    print("CLIMATE", cl["period"], cl["annual_temp_trend_c_per_decade"], cl["month_normal_1991_2020"])
    mc = await tools.compare_models(ctx)
    print("MODELS", mc["days"][0])
    mr = await tools.get_marine(ctx, "Visakhapatnam")
    print("MARINE", mr.get("available"), mr.get("current"))
    av = await tools.get_aviation(ctx, "VIDP")
    print("METAR", av.get("raw_metar"), av.get("flight_category"))
    async for e in agent.run_offline("will it rain in Mumbai tomorrow?", tools.ChatContext(lat=16.5, lon=80.6)):
        if e["type"] != "card": print(e)
    await __import__("app.services.http", fromlist=["x"]).close_client()

asyncio.run(main())
