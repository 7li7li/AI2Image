function normalizeModel(model: string) {
  return String(model || "").trim();
}

function uniqueModels(models: string[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of models) {
    const model = normalizeModel(item);
    const key = model.toLowerCase();
    if (!model || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(model);
  }
  return result;
}

function prioritizeDefault(defaultModel: string, models: string[]) {
  const normalizedDefault = normalizeModel(defaultModel);
  if (!normalizedDefault) {
    return models;
  }
  const matchedDefault = models.find((model) => model.toLowerCase() === normalizedDefault.toLowerCase());
  if (!matchedDefault) {
    return models;
  }
  return [matchedDefault, ...models.filter((model) => model !== matchedDefault)];
}

export function isImageGenerationModel(model: string) {
  const normalized = normalizeModel(model).toLowerCase();
  return (
    normalized.includes("image") ||
    normalized.includes("imagen") ||
    normalized.includes("gpt-image") ||
    normalized.includes("nano-banana")
  );
}

export function imageModelOptions(defaultModel: string, models: string[]) {
  const imageModels = models.filter(isImageGenerationModel);
  return prioritizeDefault(defaultModel, uniqueModels(imageModels));
}

export function textModelOptions(defaultModel: string, models: string[]) {
  const textModels = models.filter((model) => !isImageGenerationModel(model));
  return prioritizeDefault(defaultModel, uniqueModels(textModels));
}
