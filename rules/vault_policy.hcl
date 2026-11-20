# 초안: 두 키 사용을 파이프라인 담당자와 합의한 뒤 등록한다. -> 말 해둠
# transit 마운트 기준. 키 생성·조회·삭제·회전 권한은 Job에 부여하지 않는다.
path "transit/hmac/payment-id/sha2-256" {
  capabilities = ["update"]
}

path "transit/hmac/household-id/sha2-256" {
  capabilities = ["update"]
}