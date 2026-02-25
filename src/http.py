"""
HTTP / REST API entry point — placeholder for future FastAPI integration.

All business logic lives in src.services.*  and is already
framework-agnostic, so wiring it to FastAPI is straightforward:

    from fastapi import FastAPI
    from src.services.listing_service import ListingService
    from src.services.search_service import SearchService
    from src.services.match_service import MatchService

Example skeleton (to be implemented):

    app = FastAPI(title="Agora API", version="1.0.0")

    @app.post("/listings")
    async def create_listing(payload: ListingCreate) -> ListingResponse:
        return ListingService().post(payload.to_domain())

    @app.get("/search")
    async def search(q: str, limit: int = 10) -> list[ListingResponse]:
        return SearchService().search(q, limit=limit)

    @app.get("/match/{buy_id}")
    async def match(buy_id: str, top: int = 10) -> list[MatchResponse]:
        buy_doc = ListingService().get(buy_id)
        return MatchService().match(buy_doc=buy_doc, top=top)

To run:
    uvicorn src.http:app --reload
"""
# TODO: implement FastAPI app here
