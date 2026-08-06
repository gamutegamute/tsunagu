/**
 * 避難所のキャパシティ(決定事項9・34-b)。
 *
 * 以前はバックエンドにキャパシティ用のカラムが無く、この端末のlocalStorageに
 * 保存していたが(本部PC間でも共有されない問題があった)、GET /api/dashboard
 * のshelter.capacityとしてサーバーから直接返るようになったため、ここは
 * APIレスポンスからnull安全に読み取るだけの薄いヘルパーになった。書き込みは
 * 避難所作成時にPOST /api/sheltersのペイロードへcapacityを含めるだけで完結し、
 * 別途保存操作は不要(AddShelterModal.jsx参照)。
 */
export function getShelterCapacity(shelter) {
  return shelter?.capacity ?? null;
}
