import SwiftUI

// MARK: - Skeleton loading placeholders (doc §9)
//
// Loading states show content-shaped skeletons instead of a blank pane or a
// lone spinner, so the layout is legible before data lands.

/// A single pulsing placeholder bar.
struct SkeletonBar: View {
    var width: CGFloat? = nil
    var height: CGFloat = 12
    var radius: CGFloat = 6
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    var body: some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(Color.primary.opacity(pulse ? 0.11 : 0.05))
            .frame(width: width, height: height)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { pulse = true }
            }
    }
}

/// A card-shaped skeleton: a short title bar over a few text lines.
struct SkeletonCard: View {
    var lines: Int = 3
    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            SkeletonBar(width: 120, height: 12)
            ForEach(0..<max(1, lines), id: \.self) { _ in SkeletonBar(height: 10) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
    }
}

/// Full-page skeleton for a screen whose primary data is loading — a KPI strip
/// over a couple of content cards.
struct SkeletonScreen: View {
    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s5) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: Theme.s3), count: 5),
                      spacing: Theme.s3) {
                ForEach(0..<5, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: Theme.s3) {
                        SkeletonBar(width: 26, height: 26, radius: 8)
                        SkeletonBar(width: 110, height: 20)
                        SkeletonBar(width: 64, height: 9)
                    }
                    .padding(Theme.s4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .cardSurface()
                }
            }
            HStack(alignment: .top, spacing: Theme.s4) {
                SkeletonCard(lines: 4)
                SkeletonCard(lines: 4)
            }
            SkeletonCard(lines: 5)
        }
    }
}

/// A skeleton watchlist row (instrument-list placeholder).
struct SkeletonRow: View {
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                SkeletonBar(width: 96, height: 10)
                SkeletonBar(width: 60, height: 8)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                SkeletonBar(width: 44, height: 10)
                SkeletonBar(width: 54, height: 8)
            }
        }
        .padding(.horizontal, Theme.s3).padding(.vertical, 8)
    }
}
