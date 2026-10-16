from fastapi import APIRouter, Depends

from game import Game
from game.server import GameContext
from .models import CampaignEventJs, GameJs

router: APIRouter = APIRouter(prefix="/game")


@router.get("/", operation_id="get_game_state", response_model=GameJs)
def game_state(game: Game | None = Depends(GameContext.get)) -> GameJs | None:
    if game is None:
        return None
    return GameJs.from_game(game)


@router.get(
    "/history",
    operation_id="get_campaign_history",
    response_model=list[CampaignEventJs],
)
def campaign_history(
    limit: int = 100,
    game: Game | None = Depends(GameContext.get),
) -> list[CampaignEventJs]:
    if game is None:
        return []
    bounded_limit = max(0, min(500, limit))
    return CampaignEventJs.from_game(game, bounded_limit)
