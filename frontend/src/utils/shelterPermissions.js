export function canOperateShelter(user, shelterId) {
  return Boolean(user && (user.shelter_ids?.includes(shelterId)
    || (user.role === "hq" && user.shelter_ids?.includes("*"))));
}
