"""Executable contracts: retain extra fields and represent missing readings as null."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a JSON number")
    return value


Number = Annotated[float, BeforeValidator(number)]
Integer = Annotated[int, BeforeValidator(number)]
Level = Annotated[int, Field(ge=0, le=3)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)


class Timestamped(WireModel):
    ts: AwareDatetime

    @field_validator("ts")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class Vitals(WireModel):
    heart_rate_bpm: Integer | None = Field(default=None, ge=20, le=250)
    hr_quality: Number = Field(ge=0, le=1)
    resp_rate_bpm: None = None
    body_temp_c: Number | None = Field(default=None, ge=30, le=45)

    @model_validator(mode="after")
    def unreliable_pulse(self):
        if self.hr_quality < 0.4:
            self.heart_rate_bpm = None
        return self


class Motion(WireModel):
    activity: Literal["moving", "still"]
    still_for_s: Integer = Field(ge=0)


class Cabin(WireModel):
    temp_c: Number | None = None
    humidity_pct: Integer | None = Field(default=None, ge=0, le=100)
    dew_point_c: Number | None = None
    heat_index_c: Number | None = None
    condensation_risk: Literal["low", "medium", "high"] | None = None


class TelemetryPayload(Timestamped):
    device_id: str = Field(min_length=1)
    met_s: Integer = Field(ge=0)
    crew_id: str | None = None
    vitals: Vitals
    motion: Motion
    cabin: Cabin
    alerts: list[str] = Field(default_factory=list)


class CheckinData(WireModel):
    action: Literal["in", "out"]


class InactivityData(WireModel):
    still_for_s: Integer = Field(ge=1)
    threshold_s: Integer = Field(ge=1)


class ExerciseData(WireModel):
    exercise: Literal["pushup"]
    reps: Integer = Field(ge=1)
    duration_s: Integer = Field(ge=1)
    cadence_rpm: Number = Field(gt=0)


class EventPayload(Timestamped):
    device_id: str = Field(min_length=1)
    crew_id: str | None = None
    type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    data: dict

    @model_validator(mode="after")
    def event_data(self):
        models = {"crew_checkin": CheckinData, "inactivity": InactivityData, "exercise_summary": ExerciseData}
        if self.type in models:
            self.data = models[self.type].model_validate(self.data).model_dump(mode="json")
            if self.type != "exercise_summary" and not self.crew_id:
                raise ValueError("This event requires a crew_id")
            expected = "medium" if self.type == "inactivity" else "info"
            if self.severity != expected:
                raise ValueError(f"{self.type} requires severity {expected}")
        return self


class BloodPressure(WireModel):
    systolic: Integer | None = Field(default=None, ge=60, le=260)
    diastolic: Integer | None = Field(default=None, ge=30, le=160)

    @model_validator(mode="after")
    def order(self):
        if self.systolic is not None and self.diastolic is not None and self.diastolic >= self.systolic:
            raise ValueError("Diastolic pressure must be lower than systolic pressure")
        return self


class ManualCheckPayload(Timestamped):
    crew_id: str = Field(min_length=1)
    blood_pressure: BloodPressure | None = None
    glucose_mg_dl: Number | None = Field(default=None, ge=20, le=600)
    mood: Integer | None = Field(default=None, ge=1, le=5)


class SystemAssessment(WireModel):
    level: Level | None
    reasons: list[str]


class Systems(WireModel):
    cardiovascular: SystemAssessment
    neuro: SystemAssessment
    musculoskeletal: SystemAssessment
    environment: SystemAssessment


class Trend(WireModel):
    indicator: str
    label: str
    unit: str
    basis: Literal["count", "time"]
    x_unit: str
    points: list[tuple[Number, Number]]
    slope: Number
    intercept: Number
    horizon: Number
    projected: Number
    threshold: Number | None = None
    threshold_level: Level | None = None
    crosses_in: Number | None = None


class RiskAssessment(Timestamped):
    crew_id: str | None
    overall_level: Level | None
    systems: Systems
    trends: list[Trend] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    earth_summary: str | None = None


class CrewProfile(WireModel):
    crew_id: str
    name: str
    role: str | None
    assigned: bool


class LatestCrewResponse(WireModel):
    crew_id: str
    crew_name: str
    crew_role: str | None
    assigned: bool
    telemetry: TelemetryPayload | None
    assessment: RiskAssessment | None
    last_exercise: EventPayload | None = None
    assessment_error: str | None = None
