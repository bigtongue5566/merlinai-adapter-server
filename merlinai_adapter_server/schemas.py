import uuid
from typing import Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

JsonDict = Dict[str, Any]


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ContentPart(FlexibleModel):
    model_config = ConfigDict(extra="ignore")

    type: Optional[str] = None
    text: Optional[str] = None
    input_text: Optional[str] = None
    content: Optional[str] = None


class ToolFunction(FlexibleModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[JsonDict] = None


class ToolDefinition(FlexibleModel):
    type: Optional[str] = "function"
    function: Optional[ToolFunction] = None


def build_function_tool_payload(*, name: str, description: str, input_schema: Type[BaseModel]) -> JsonDict:
    return ToolDefinition(
        type="function",
        function=ToolFunction(
            name=name,
            description=description,
            parameters=input_schema.model_json_schema(),
        ),
    ).model_dump(exclude_none=True)


class ToolChoiceFunction(FlexibleModel):
    name: Optional[str] = None


class ToolChoiceObject(FlexibleModel):
    type: Optional[str] = None
    function: Optional[ToolChoiceFunction] = None


class OpenAIFunctionCall(FlexibleModel):
    name: Optional[str] = None
    arguments: Optional[Any] = None


class OpenAIToolCall(FlexibleModel):
    id: Optional[str] = None
    type: Optional[str] = "function"
    function: Optional[OpenAIFunctionCall] = None


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[OpenAIToolCall]] = None
    content: Optional[Union[str, List[Union[ContentPart, JsonDict, str]]]] = None


class OpenAIRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: List[Message]
    stream: Optional[bool] = False
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, ToolChoiceObject]] = None


class NormalizedFunctionCall(BaseModel):
    name: str
    arguments: str


class NormalizedToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex}")
    type: Literal["function"] = "function"
    function: NormalizedFunctionCall


class ToolPromptPayloadCall(BaseModel):
    name: str
    arguments: JsonDict = Field(default_factory=dict)


class ToolPromptToolCallsPayload(BaseModel):
    type: Literal["tool_calls"] = "tool_calls"
    tool_calls: List[ToolPromptPayloadCall]


class ToolPromptMessagePayload(BaseModel):
    type: Literal["message"] = "message"
    content: str


class ToolPromptPayloadSchema(RootModel[Union[ToolPromptToolCallsPayload, ToolPromptMessagePayload]]):
    pass


def build_tool_prompt_payload_json_schema() -> JsonDict:
    input_schema = ToolPromptPayloadSchema
    return input_schema.model_json_schema()


class OpenAIResponseMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[NormalizedToolCall]] = None


class OpenAIChoice(BaseModel):
    index: int = 0
    message: OpenAIResponseMessage
    finish_reason: str


class OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4()}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChoice]
    usage: OpenAIUsage = Field(default_factory=OpenAIUsage)


class OpenAIStreamDelta(BaseModel):
    role: Optional[Literal["assistant"]] = None
    content: Optional[str] = None
    tool_calls: Optional[List[JsonDict]] = None


class OpenAIStreamChoice(BaseModel):
    index: int = 0
    delta: OpenAIStreamDelta
    finish_reason: Optional[str] = None


class OpenAIChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: List[OpenAIStreamChoice]


class OpenAIModel(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str = "merlin"


class OpenAIModelsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: List[OpenAIModel]


class MerlinMessagePayload(BaseModel):
    childId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    context: str = ""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parentId: str = "root"


class MerlinMcpConfig(BaseModel):
    isEnabled: bool = False


class MerlinMetadata(BaseModel):
    deepResearch: bool = False
    merlinMagic: bool = False
    noTask: bool = True
    proFinderMode: bool = False
    mcpConfig: MerlinMcpConfig = Field(default_factory=MerlinMcpConfig)
    isWebpageChat: bool = False
    webAccess: bool = True


class MerlinPayload(BaseModel):
    attachments: List[Any] = Field(default_factory=list)
    chatId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    language: str = "AUTO"
    message: MerlinMessagePayload
    mode: str = "UNIFIED_CHAT"
    model: str
    metadata: MerlinMetadata = Field(default_factory=MerlinMetadata)


class MerlinEventData(FlexibleModel):
    text: Optional[str] = None
    content: Optional[str] = None
    toolCalls: Optional[List[JsonDict]] = None
    tool_calls: Optional[List[JsonDict]] = None


class MerlinEvent(FlexibleModel):
    data: MerlinEventData = Field(default_factory=MerlinEventData)

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_data(cls, value: Any) -> Any:
        return value if isinstance(value, dict) else {}


class FirebaseSignInResponse(BaseModel):
    idToken: str
    refreshToken: str
    expiresIn: str


class FirebaseRefreshResponse(BaseModel):
    id_token: str
    refresh_token: str
    expires_in: str


def model_dump_compat(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [model_dump_compat(item) for item in value]
    if isinstance(value, dict):
        return {key: model_dump_compat(item) for key, item in value.items()}
    return value
