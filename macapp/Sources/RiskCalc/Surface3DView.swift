import SwiftUI
import SceneKit

/// True 3D volatility surface (SceneKit): X = call delta, Z = time to expiry,
/// Y (height) + colour = implied vol. Orbit with the mouse. Built as a coloured
/// triangle mesh from the calibrated SABR grid.
struct Surface3DView: NSViewRepresentable {
    let underlying: String
    let rows: [VolSurfaceRow]
    let deltas: [Double]

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var sig = "" }

    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.backgroundColor = .clear
        view.antialiasingMode = .multisampling4X
        view.scene = scene()
        context.coordinator.sig = signature
        return view
    }

    func updateNSView(_ view: SCNView, context: Context) {
        guard context.coordinator.sig != signature else { return }   // keep camera unless data changed
        view.scene = scene()
        context.coordinator.sig = signature
    }

    private var signature: String { "\(underlying)|\(rows.count)|\(deltas.count)|\(rows.first?.expiry ?? "")" }

    // MARK: grid

    private struct Grid {
        let xs: [Double]; let ts: [Double]; let labels: [String]
        let iv: [[Double]]; let lo: Double; let hi: Double
    }

    private func grid() -> Grid? {
        let valid = rows.compactMap { r -> (Double, String, [VolSurfaceCell])? in
            guard let t = r.t else { return nil }
            return (t, r.expiry, r.cells)
        }.sorted { $0.0 < $1.0 }
        guard valid.count >= 2, deltas.count >= 2 else { return nil }

        var mat: [[Double]] = []
        var all: [Double] = []
        for (_, _, cells) in valid {
            var row = [Double?](repeating: nil, count: deltas.count)
            for j in deltas.indices where j < cells.count {
                if let iv = cells[j].iv, iv.isFinite { row[j] = iv }
            }
            var last: Double?
            for j in row.indices { if row[j] == nil { row[j] = last } else { last = row[j] } }
            var next: Double?
            for j in stride(from: row.count - 1, through: 0, by: -1) {
                if row[j] == nil { row[j] = next } else { next = row[j] }
            }
            let filled = row.map { $0 ?? 0 }
            mat.append(filled)
            all += filled.filter { $0 > 0 }
        }
        let lo = all.min() ?? 0, hi = all.max() ?? 1
        return Grid(xs: deltas, ts: valid.map(\.0), labels: valid.map(\.1),
                    iv: mat, lo: lo, hi: max(hi, lo + 1e-6))
    }

    // MARK: scene

    private func scene() -> SCNScene {
        let s = SCNScene()
        guard let g = grid() else { return s }
        s.rootNode.addChildNode(axisFrame(g))
        s.rootNode.addChildNode(surfaceNode(g))
        s.rootNode.addChildNode(wireNode(g))
        let cam = SCNNode()
        cam.camera = SCNCamera()
        cam.camera!.fieldOfView = 42
        cam.position = SCNVector3(3.2, 2.6, 3.7)
        cam.look(at: SCNVector3(0, 0.45, 0))
        s.rootNode.addChildNode(cam)
        return s
    }

    private let yMax = 1.2

    /// Axis box: floor grid, back/left IV walls, emphasised X/Y/Z axes, tick
    /// labels (Δ, IV %, expiries) and axis titles — so it reads as a 3D chart.
    private func axisFrame(_ g: Grid) -> SCNNode {
        let root = SCNNode()
        let grid = NSColor.white.withAlphaComponent(0.14)
        let axis = NSColor.white.withAlphaComponent(0.40)

        // floor grid (y = 0)
        for d in stride(from: 0.0, through: 1.0, by: 0.25) {
            root.addChildNode(line(vec(d * 2 - 1, 0, -1), vec(d * 2 - 1, 0, 1), grid))
        }
        for k in 0...4 {
            let z = Double(k) / 4 * 2 - 1
            root.addChildNode(line(vec(-1, 0, z), vec(1, 0, z), grid))
        }
        // IV gridlines on the back (z=-1) and left (x=-1) walls
        for k in 0...3 {
            let y = Double(k) / 3 * yMax
            root.addChildNode(line(vec(-1, y, -1), vec(1, y, -1), grid))
            root.addChildNode(line(vec(-1, y, -1), vec(-1, y, 1), grid))
        }
        // emphasised axes: delta along the front-bottom, tenor along the left-
        // bottom, IV up the back-left vertical edge (kept on separate edges).
        root.addChildNode(line(vec(-1, 0, 1), vec(1, 0, 1), axis))      // X — delta (front)
        root.addChildNode(line(vec(-1, 0, 1), vec(-1, 0, -1), axis))    // Z — tenor (left)
        root.addChildNode(line(vec(-1, 0, -1), vec(-1, yMax, -1), axis))  // Y — IV (back-left)

        // X — delta: front-bottom edge
        for d in [0.0, 0.5, 1.0] {
            root.addChildNode(label(d == 0 ? "0" : (d == 1 ? "1.0" : "0.5"), vec(d * 2 - 1, -0.08, 1.16)))
        }
        root.addChildNode(label("Δ call", vec(0.35, -0.22, 1.4), 0.14))

        // Y — IV: back-left vertical edge
        for k in 0...2 {
            let frac = Double(k) / 2
            root.addChildNode(label(pct(g.lo + frac * (g.hi - g.lo)), vec(-1.18, frac * yMax, -1.12)))
        }
        root.addChildNode(label("IV %", vec(-1.2, yMax + 0.16, -1.12), 0.14))

        // Z — tenor: left-bottom edge running into depth
        root.addChildNode(label(short(g.labels.first ?? ""), vec(-1.34, -0.1, 1.0)))
        root.addChildNode(label(short(g.labels.last ?? ""), vec(-1.34, -0.1, -1.0)))
        root.addChildNode(label("срок", vec(-1.62, -0.22, 0), 0.14))
        return root
    }

    private func line(_ a: SCNVector3, _ b: SCNVector3, _ color: NSColor, _ r: CGFloat = 0.005) -> SCNNode {
        let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z
        let len = CGFloat(sqrt(Double(dx * dx + dy * dy + dz * dz)))
        let cyl = SCNCylinder(radius: r, height: max(len, 1e-4))
        let m = SCNMaterial(); m.diffuse.contents = color; m.lightingModel = .constant
        cyl.materials = [m]
        let node = SCNNode(geometry: cyl)
        node.position = SCNVector3((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)
        node.look(at: b, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        return node
    }

    private func label(_ s: String, _ pos: SCNVector3, _ size: CGFloat = 0.1) -> SCNNode {
        let t = SCNText(string: s, extrusionDepth: 0)
        t.font = NSFont.systemFont(ofSize: 1)
        t.flatness = 0.3
        let m = SCNMaterial(); m.diffuse.contents = NSColor.white.withAlphaComponent(0.8); m.lightingModel = .constant
        t.materials = [m]
        let n = SCNNode(geometry: t)
        n.scale = SCNVector3(size, size, size)
        let (lo, hi) = t.boundingBox
        n.pivot = SCNMatrix4MakeTranslation((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0)
        n.position = pos
        n.constraints = [SCNBillboardConstraint()]
        return n
    }

    private func pct(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }
    private func short(_ s: String) -> String { s.count >= 5 ? String(s.suffix(5)) : s }

    private func vec(_ x: Double, _ y: Double, _ z: Double) -> SCNVector3 {
        SCNVector3(CGFloat(x), CGFloat(y), CGFloat(z))
    }

    private func xyz(_ g: Grid, _ i: Int, _ j: Int) -> (Double, Double, Double) {
        let x = g.xs[j] * 2 - 1                                   // delta 0..1 → -1..1
        let tlo = g.ts.first!, thi = max(g.ts.last!, tlo + 1e-9)
        let z = (g.ts[i] - tlo) / (thi - tlo) * 2 - 1             // tenor → -1..1
        let h = (g.iv[i][j] - g.lo) / (g.hi - g.lo)              // iv → 0..1
        return (x, h * 1.2, z)
    }

    private func surfaceNode(_ g: Grid) -> SCNNode {
        let cols = g.xs.count, rs = g.ts.count
        var verts: [SCNVector3] = []
        var colorComponents: [Float] = []
        for i in 0..<rs {
            for j in 0..<cols {
                let (x, y, z) = xyz(g, i, j)
                verts.append(vec(x, y, z))
                let (r, gr, b) = heatRGB((g.iv[i][j] - g.lo) / (g.hi - g.lo))
                colorComponents += [r, gr, b, 1]
            }
        }
        var idx: [Int32] = []
        for i in 0..<(rs - 1) {
            for j in 0..<(cols - 1) {
                let a = Int32(i * cols + j), b = Int32(i * cols + j + 1)
                let c = Int32((i + 1) * cols + j), d = Int32((i + 1) * cols + j + 1)
                idx += [a, c, b, b, c, d]
            }
        }
        let vSrc = SCNGeometrySource(vertices: verts)
        let cData = Data(bytes: colorComponents, count: colorComponents.count * MemoryLayout<Float>.size)
        let cSrc = SCNGeometrySource(data: cData, semantic: .color, vectorCount: verts.count,
                                     usesFloatComponents: true, componentsPerVector: 4,
                                     bytesPerComponent: MemoryLayout<Float>.size, dataOffset: 0,
                                     dataStride: MemoryLayout<Float>.size * 4)
        let geo = SCNGeometry(sources: [vSrc, cSrc],
                              elements: [SCNGeometryElement(indices: idx, primitiveType: .triangles)])
        let m = SCNMaterial()
        m.isDoubleSided = true
        m.lightingModel = .constant
        geo.materials = [m]
        return SCNNode(geometry: geo)
    }

    /// Thin wireframe over the mesh for depth perception.
    private func wireNode(_ g: Grid) -> SCNNode {
        let cols = g.xs.count, rs = g.ts.count
        var verts: [SCNVector3] = []
        var idx: [Int32] = []
        for i in 0..<rs {
            for j in 0..<cols {
                let (x, y, z) = xyz(g, i, j)
                verts.append(vec(x, y + 0.002, z))
            }
        }
        for i in 0..<rs {
            for j in 0..<cols {
                let p = Int32(i * cols + j)
                if j < cols - 1 { idx += [p, Int32(i * cols + j + 1)] }
                if i < rs - 1 { idx += [p, Int32((i + 1) * cols + j)] }
            }
        }
        let geo = SCNGeometry(sources: [SCNGeometrySource(vertices: verts)],
                              elements: [SCNGeometryElement(indices: idx, primitiveType: .line)])
        let m = SCNMaterial()
        m.lightingModel = .constant
        m.diffuse.contents = NSColor.white.withAlphaComponent(0.12)
        geo.materials = [m]
        return SCNNode(geometry: geo)
    }

    private func heatRGB(_ t: Double) -> (Float, Float, Float) {
        let h = max(0, min(1, (1 - t))) * 0.62                    // blue (low) → red (high)
        let s = 0.85, v = 0.95
        let i = Int(h * 6) % 6
        let f = h * 6 - Double(Int(h * 6))
        let p = v * (1 - s), q = v * (1 - f * s), w = v * (1 - (1 - f) * s)
        let rgb: (Double, Double, Double)
        switch i {
        case 0: rgb = (v, w, p)
        case 1: rgb = (q, v, p)
        case 2: rgb = (p, v, w)
        case 3: rgb = (p, q, v)
        case 4: rgb = (w, p, v)
        default: rgb = (v, p, q)
        }
        return (Float(rgb.0), Float(rgb.1), Float(rgb.2))
    }
}
