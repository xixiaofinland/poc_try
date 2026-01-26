from pydantic import BaseModel, ConfigDict, Field


class InstrumentDescription(BaseModel):
    category: str = Field(
        default="",
        description="Instrument category (e.g. guitar, violin).",
        examples=["electric guitar"],
    )
    brand: str = Field(default="", description="Instrument brand.", examples=["Fender"])
    model: str = Field(default="", description="Instrument model.", examples=["Stratocaster"])
    year: str | None = Field(
        default=None,
        description="Year of manufacture if known.",
        examples=["1996", "不明"],
    )
    condition: str = Field(
        default="",
        description="Condition / wear summary.",
        examples=["Good (minor scratches)"],
    )
    materials: list[str] = Field(
        default_factory=list,
        description="Key materials (if visible / known).",
        examples=[["alder", "maple"]],
    )
    features: list[str] = Field(
        default_factory=list,
        description="Notable features / hardware.",
        examples=[["SSS pickups", "tremolo bridge"]],
    )
    notes: str = Field(
        default="",
        description="Extra notes / caveats from the description model.",
        examples=["Includes gig bag; serial number not visible."],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "category": "electric guitar",
                    "brand": "Fender",
                    "model": "Stratocaster",
                    "year": "1996",
                    "condition": "Good (minor scratches)",
                    "materials": ["alder", "maple"],
                    "features": ["SSS pickups", "tremolo bridge"],
                    "notes": "Includes gig bag; serial number not visible.",
                }
            ]
        }
    )


class ValuationResult(BaseModel):
    price_jpy: int = Field(
        description="Estimated fair price in JPY.",
        examples=[120000],
        ge=0,
    )
    range_jpy: tuple[int, int] = Field(
        description="Low / high price range in JPY.",
        examples=[[90000, 150000]],
    )
    confidence: float = Field(
        description="Confidence score between 0 and 1.",
        examples=[0.72],
        ge=0,
        le=1,
    )
    rationale: str = Field(
        description="Valuation rationale (Japanese).",
        examples=["参考データの価格帯と状態から、このレンジが妥当と判断しました。"],
    )
    evidence: list[str] = Field(
        description="Evidence bullets (Japanese).",
        examples=[["類似モデルの出品: 95,000〜140,000円（状態: 良）"]],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "price_jpy": 120000,
                    "range_jpy": [90000, 150000],
                    "confidence": 0.72,
                    "rationale": "参考データの価格帯と状態から、このレンジが妥当と判断しました。",
                    "evidence": ["類似モデルの出品: 95,000〜140,000円（状態: 良）"],
                }
            ]
        }
    )
