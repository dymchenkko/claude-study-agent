// OCR for scanned PDF pages with Apple Vision (macOS 13+, no install needed).
//
//   ocr <file.pdf> <pages: 1,3,4 | all> [languages: ja-JP,en-US | auto]
//
// Prints one JSON object {"<page>": "<text>", ...}. Lines are in reading order
// (top to bottom, then left to right). `study` compiles this once into .tools/bin/ocr.
import Foundation
import PDFKit
import Vision

let args = CommandLine.arguments
guard args.count >= 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: ocr <file.pdf> <pages|all> [langs|auto]\n".data(using: .utf8)!)
    exit(2)
}
let pages = args[2] == "all" ? Array(1...max(doc.pageCount, 1))
                             : args[2].split(separator: ",").compactMap { Int($0) }
let langs = args.count > 3 && args[3] != "auto" ? args[3].split(separator: ",").map(String.init) : []

func render(_ page: PDFPage) -> CGImage? {
    let box = page.bounds(for: .mediaBox)
    let scale = 300.0 / 72.0  // 300 dpi
    let w = Int(box.width * scale), h = Int(box.height * scale)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -box.minX, y: -box.minY)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

var out: [String: String] = [:]
for n in pages where n >= 1 && n <= doc.pageCount {
    guard let page = doc.page(at: n - 1), let image = render(page) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    if langs.isEmpty { req.automaticallyDetectsLanguage = true } else { req.recognitionLanguages = langs }
    try? VNImageRequestHandler(cgImage: image).perform([req])
    let obs = (req.results ?? []).sorted {
        // same line if vertical centres are close; Vision's y axis points up
        abs($0.boundingBox.midY - $1.boundingBox.midY) < 0.01
            ? $0.boundingBox.minX < $1.boundingBox.minX : $0.boundingBox.midY > $1.boundingBox.midY
    }
    out[String(n)] = obs.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}
let data = try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
